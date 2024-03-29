Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm is designed to be used in conjunction with the rest of the OpenStack
related charms in the charm store to virtualize the network that Nova Compute
instances plug into.

This charm provides the Web UI component which contains the
contrail-web-controller service.
Only OpenStack Icehouse or newer is supported.

Usage
-----

Keystone, Contrail Configuration and Cassandra are prerequisite services to
deploy.

Once ready, deploy and relate as follows:

    juju deploy contrail-webui
    juju add-relation contrail-webui keystone
    juju add-relation contrail-webui:contrail_api contrail-configuration:contrail-api
    juju add-relation contrail-webui:contrail_discovery contrail-configuration:contrail-discovery
    juju add-relation contrail-webui:cassandra cassandra:database

Install Sources
---------------

The version of OpenContrail installed when deploying can be changed using the
'install-sources' option. This is a multilined value that may refer to PPAs or
Deb repositories.

High Availability (HA)
----------------------

Multiple units of this charm can be deployed to support HA deployments:

    juju add-unit contrail-webui

Relating to haproxy charm (website relation) allows multiple units to be load
balanced:

    juju add-relation contrail-webui haproxy
