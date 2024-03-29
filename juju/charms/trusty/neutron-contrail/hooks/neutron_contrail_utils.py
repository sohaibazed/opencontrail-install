import os
import pwd
import shutil
from socket import gethostbyname, gethostname
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)

import apt_pkg
import yaml

import netaddr
import netifaces

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    relation_type,
    remote_unit
)

from charmhelpers.core.host import service_restart, service_start

from charmhelpers.core.templating import render

apt_pkg.init()

def dpkg_version(pkg):
    try:
        return check_output(["dpkg-query", "-f", "${Version}\\n", "-W", pkg]).rstrip()
    except CalledProcessError:
        return None

OPENSTACK_VERSION = dpkg_version("nova-compute")

config = config()

def api_port():
    return 8082

def configure_vrouter():
    # run external script to configure vrouter
    args = ["./create-vrouter.sh"]
    iface = config.get("vhost-interface")
    if iface:
        args.append(iface)
    check_call(args, cwd="scripts")

def contrail_api_ctx():
    ip = config.get("contrail-api-ip")
    if ip:
        port = config.get("contrail-api-port")
        return { "api_server": ip,
                 "api_port": port if port is not None else api_port() }

    ctxs = [ { "api_server": gethostbyname(relation_get("private-address", unit, rid)),
               "api_port": port }
             for rid in relation_ids("contrail-api")
             for unit, port in
             ((unit, relation_get("port", unit, rid)) for unit in related_units(rid))
             if port ]
    return ctxs[0] if ctxs else {}

def contrail_discovery_ctx():
    ip = config.get("discovery-server-ip")
    if ip:
        return { "discovery_server": ip,
                 "discovery_port": discovery_port() }

    ctxs = [ { "discovery_server": vip if vip \
                 else gethostbyname(relation_get("private-address", unit, rid)),
               "discovery_port": port }
             for rid in relation_ids("contrail-discovery")
             for unit, port, vip in
             ((unit, relation_get("port", unit, rid), relation_get("vip", unit, rid))
              for unit in related_units(rid))
             if port ]
    return ctxs[0] if ctxs else {}

def control_node_ctx():
    return { "control_nodes": [ gethostbyname(relation_get("private-address", unit, rid))
                                for rid in relation_ids("control-node")
                                for unit in related_units(rid) ] }

def disable_vrouter_vgw():
    if os.path.exists("/etc/sysctl.d/60-vrouter-vgw.conf"):
        # unset sysctl options
        os.remove("/etc/sysctl.d/60-vrouter-vgw.conf")
        check_call(["sysctl", "-qw", "net.ipv4.ip_forward=0"])

def discovery_port():
    return 5998

def enable_vrouter_vgw():
    if not os.path.exists("/etc/sysctl.d/60-vrouter-vgw.conf"):
        # set sysctl options
        shutil.copy("files/60-vrouter-vgw.conf", "/etc/sysctl.d")
        service_start("procps")

def fix_nodemgr():
    # add files missing from contrail-nodemgr package
    shutil.copy("files/contrail-nodemgr-vrouter.ini",
                "/etc/contrail/supervisord_vrouter_files")
    pw = pwd.getpwnam("contrail")
    os.chown("/etc/contrail/supervisord_vrouter_files/contrail-nodemgr-vrouter.ini",
             pw.pw_uid, pw.pw_gid)
    shutil.copy("files/contrail-vrouter.rules",
                "/etc/contrail/supervisord_vrouter_files")
    os.chown("/etc/contrail/supervisord_vrouter_files/contrail-vrouter.rules",
             pw.pw_uid, pw.pw_gid)
    shutil.copy("files/contrail-vrouter-nodemgr", "/etc/init.d")
    os.chmod("/etc/init.d/contrail-vrouter-nodemgr", 0755)
    service_restart("supervisor-vrouter")

def fix_permissions():
    os.chmod("/etc/contrail", 0755)
    os.chown("/etc/contrail", 0, 0)

def fix_vrouter_scripts():
    # certain files need to be present for packages
    if not os.path.exists("/opt/contrail/bin"):
        os.makedirs("/opt/contrail/bin")
        os.symlink("/bin/true", "/opt/contrail/bin/vrouter-pre-start.sh")
        os.symlink("/bin/true", "/opt/contrail/bin/vrouter-post-start.sh")
        os.symlink("/bin/true", "/opt/contrail/bin/vrouter-pre-stop.sh")

def gateway():
    """Return the host gateway"""
    for line in check_output(["route", "-n"]).splitlines()[2:]:
        l = line.split()
        if "G" in l[3]:
            return l[1]
    return None

def identity_admin_ctx():
    ctxs = [ { "auth_host": gethostbyname(hostname),
               "auth_port": relation_get("service_port", unit, rid) }
             for rid in relation_ids("identity-admin")
             for unit, hostname in
             ((unit, relation_get("service_hostname", unit, rid)) for unit in related_units(rid))
             if hostname ]
    return ctxs[0] if ctxs else {}

def ifdown(interfaces=None):
    """ifdown an interface or all interfaces"""
    log("Taking down {}".format(interfaces if interfaces else "interfaces"))
    check_call(["ifdown"] + interfaces if interfaces else ["-a"])

def ifup(interfaces=None):
    """ifup an interface or all interfaces"""
    log("Bringing up {}".format(interfaces if interfaces else "interfaces"))
    check_call(["ifup"] + interfaces if interfaces else ["-a"])

def modprobe(module, auto_load=False, dkms_autoinstall=False):
    """Load a kernel module.

    Allows loading of a kernel module.

    'dkms_autoinstall' is useful for DKMS kernel modules. Juju often upgrades
    units to newer kernels before charm install, which won't be used until the
    machine is rebooted. In these cases, some modules may not be compiled for
    the newer kernel. Setting this argument to True will ensure these modules
    are compiled for newer kernels.

    :param module: module to load
    :param auto_load: load module on boot (default False)
    :param dkms_autoinstall: invoke DKMS autoinstall for other kernels
                             (default False)
    """
    log("Loading kernel module {}".format(module))
    check_call(["modprobe", module])
    if auto_load:
        with open("/etc/modules", "a") as modules:
            modules.write(module)
            modules.write("\n")
    if dkms_autoinstall:
        current = check_output(["uname", "-r"]).rstrip()
        for kernel in os.listdir("/lib/modules"):
            if kernel == current:
                continue
            log("DKMS auto installing for kernel {}".format(kernel))
            check_call(["dkms", "autoinstall", "-k", kernel])

def network_ctx():
    return { "control_network_ip": netifaces.ifaddresses("vhost0")[netifaces.AF_INET][0]["addr"] }

def neutron_metadata_ctx():
    if "local-metadata-secret" in config:
        return { "metadata_secret": config["local-metadata-secret"] }

    ctxs = [ { "metadata_secret": relation_get("shared-secret", unit, rid) }
             for rid in relation_ids("neutron-metadata")
             for unit in related_units(rid) ]
    return ctxs[0] if ctxs else {}

def provision_local_metadata():
    a_port = None
    a_ip = config.get("contrail-api-ip")
    if a_ip:
        a_port = config.get("contrail-api-port")
        if a_port is None:
            a_port = api_port()
    else:
        a_ip, a_port = [ (gethostbyname(relation_get("private-address", unit, rid)),
                          port)
                         for rid in relation_ids("contrail-api")
                         for unit, port in
                         ((unit, relation_get("port", unit, rid)) for unit in related_units(rid))
                         if port ][0]
    user, password = [ (relation_get("service_username", unit, rid),
                        relation_get("service_password", unit, rid))
                       for rid in relation_ids("identity-admin")
                       for unit in related_units(rid) ][0]
    log("Provisioning local metadata service 127.0.0.1:8775")
    check_call(["contrail-provision-linklocal",
                "--api_server_ip", a_ip,
                "--api_server_port", str(a_port),
                "--linklocal_service_name", "metadata",
                "--linklocal_service_ip", "169.254.169.254",
                "--linklocal_service_port", "80",
                "--ipfabric_service_ip", "127.0.0.1",
                "--ipfabric_service_port", "8775",
                "--oper", "add",
                "--admin_user", user,
                "--admin_password", password])

def provision_vrouter():
    host_name = gethostname()
    host_ip = netifaces.ifaddresses("vhost0")[netifaces.AF_INET][0]["addr"]
    a_port = None
    a_ip = config.get("contrail-api-ip")
    if a_ip:
        a_port = config.get("contrail-api-port")
        if a_port is None:
            a_port = api_port()
    else:
        a_ip, a_port = [ (gethostbyname(relation_get("private-address", unit, rid)),
                          port)
                         for rid in relation_ids("contrail-api")
                         for unit, port in
                         ((unit, relation_get("port", unit, rid)) for unit in related_units(rid))
                         if port ][0]
    user, password, tenant = [ (relation_get("service_username", unit, rid),
                                relation_get("service_password", unit, rid),
                                relation_get("service_tenant_name", unit, rid))
                               for rid in relation_ids("identity-admin")
                               for unit in related_units(rid) ][0]
    log("Provisioning vrouter {}".format(host_ip))
    check_call(["contrail-provision-vrouter",
                "--host_name", host_name,
                "--host_ip", host_ip,
                "--api_server_ip", a_ip,
                "--api_server_port", str(a_port),
                "--oper", "add",
                "--admin_user", user,
                "--admin_password", password,
                "--admin_tenant_name", tenant])

def remove_juju_bridge():
    # run external script to remove bridge
    check_call(["./remove-juju-bridge.sh"], cwd="scripts")

def units(relation):
    """Return a list of units for the specified relation"""
    return [ unit for rid in relation_ids(relation)
                  for unit in related_units(rid) ]

def unprovision_local_metadata():
    relation = relation_type()
    if relation and not remote_unit():
        return
    a_ip = config.previous("contrail-api-ip")
    a_port = None
    if a_ip:
        a_port = config.previous("contrail-api-port")
        if a_port is None:
            a_port = api_port()
    elif relation == "contrail-api":
        a_ip = gethostbyname(relation_get("private-address"))
        a_port = relation_get("port")
    else:
        a_ip, a_port = [ (gethostbyname(relation_get("private-address", unit, rid)),
                          relation_get("port", unit, rid))
                         for rid in relation_ids("contrail-api")
                         for unit in related_units(rid) ][0]
    user = None
    password = None
    if relation == "identity-admin":
        user = relation_get("service_username")
        password = relation_get("service_password")
    else:
        user, password = [ (relation_get("service_username", unit, rid),
                            relation_get("service_password", unit, rid))
                           for rid in relation_ids("identity-admin")
                           for unit in related_units(rid) ][0]
    log("Unprovisioning local metadata service 127.0.0.1:8775")
    check_call(["contrail-provision-linklocal",
                "--api_server_ip", a_ip,
                "--api_server_port", str(a_port),
                "--linklocal_service_name", "metadata",
                "--linklocal_service_ip", "169.254.169.254",
                "--linklocal_service_port", "80",
                "--ipfabric_service_ip", "127.0.0.1",
                "--ipfabric_service_port", "8775",
                "--oper", "del",
                "--admin_user", user,
                "--admin_password", password])

def unprovision_vrouter():
    relation = relation_type()
    if relation and not remote_unit():
        return
    host_name = gethostname()
    host_ip = netifaces.ifaddresses("vhost0")[netifaces.AF_INET][0]["addr"]
    a_ip = config.previous("contrail-api-ip")
    a_port = None
    if a_ip:
        a_port = config.previous("contrail-api-port")
        if a_port is None:
            a_port = api_port()
    elif relation == "contrail-api":
        a_ip = gethostbyname(relation_get("private-address"))
        a_port = relation_get("port")
    else:
        a_ip, a_port = [ (gethostbyname(relation_get("private-address", unit, rid)),
                          relation_get("port", unit, rid))
                         for rid in relation_ids("contrail-api")
                         for unit in related_units(rid) ][0]
    user = None
    password = None
    tenant = None
    if relation == "identity-admin":
        user = relation_get("service_username")
        password = relation_get("service_password")
        tenant = relation_get("service_tenant_name")
    else:
        user, password, tenant = [ (relation_get("service_username", unit, rid),
                                    relation_get("service_password", unit, rid),
                                    relation_get("service_tenant_name", unit, rid))
                                   for rid in relation_ids("identity-admin")
                                   for unit in related_units(rid) ][0]
    log("Unprovisioning vrouter {}".format(host_ip))
    check_call(["contrail-provision-vrouter",
                "--host_name", host_name,
                "--host_ip", host_ip,
                "--api_server_ip", a_ip,
                "--api_server_port", str(a_port),
                "--oper", "del",
                "--admin_user", user,
                "--admin_password", password,
                "--admin_tenant_name", tenant])

def vhost_ip(iface):
    # return a vhost formatted address and mask - x.x.x.x/xx
    addr = netifaces.ifaddresses(iface)[netifaces.AF_INET][0]
    ip = addr["addr"]
    cidr = netaddr.IPNetwork(ip + "/" + addr["netmask"]).prefixlen
    return ip + "/" + str(cidr)

def vhost_phys():
    # run external script to determine physical interface of vhost0
    return check_output(["scripts/vhost-phys.sh"]).rstrip()

def vrouter_ctx():
    return { "vhost_ip": vhost_ip("vhost0"),
             "vhost_gateway": gateway(),
             "vhost_physical": vhost_phys() }

def vrouter_vgw_ctx():
    ctx = {}
    vgws = config.get("virtual-gateways")
    if vgws:
        vgws = yaml.safe_load(vgws)
        map(lambda item: item.update(domain="default-domain"), vgws)
        ctx["vgws"] = vgws
    return ctx

def write_nodemgr_config():
    ctx = contrail_discovery_ctx()
    render("contrail-vrouter-nodemgr.conf",
           "/etc/contrail/contrail-vrouter-nodemgr.conf", ctx)

def write_vnc_api_config():
    ctx = {}
    ctx.update(contrail_api_ctx())
    ctx.update(identity_admin_ctx())
    render("vnc_api_lib.ini", "/etc/contrail/vnc_api_lib.ini", ctx)

def write_vrouter_config():
    ctx = {}
    ctx.update(control_node_ctx())
    ctx.update(contrail_discovery_ctx())
    ctx.update(neutron_metadata_ctx())
    ctx.update(network_ctx())
    ctx.update(vrouter_ctx())
    ctx.update(vrouter_vgw_ctx())
    render("contrail-vrouter-agent.conf",
           "/etc/contrail/contrail-vrouter-agent.conf", ctx, perms=0440)

def write_vrouter_vgw_interfaces():
    ctx = vrouter_vgw_ctx()
    render("vrouter-vgw.cfg", "/etc/network/interfaces.d/vrouter-vgw.cfg", ctx)
