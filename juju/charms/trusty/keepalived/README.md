Overview
--------

Keepalived is a routing software written in C. The main goal of this project is
to provide simple and robust facilities for loadbalancing and high-availability
to Linux system and Linux based infrastructures. Loadbalancing framework relies
on well-known and widely used Linux Virtual Server (IPVS) kernel module
providing Layer4 loadbalancing. Keepalived implements a set of checkers to
dynamically and adaptively maintain and manage loadbalanced server pool
according their health. On the other hand high-availability is achieved by VRRP
protocol. VRRP is a fundamental brick for router failover. In addition,
Keepalived implements a set of hooks to the VRRP finite state machine providing
low-level and high-speed protocol interactions. Keepalived frameworks can be
used independently or all together to provide resilient infrastructures.

Usage
-----

Once ready, deploy as follows:

    juju deploy keepalived
    juju add-relation haproxy keepalived

