from ryu.base import app_manager
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.topology import event, switches
from ryu.topology.api import (get_switch, get_link)
import networkx as nx
import json
class NetworkDiscovery(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    def __init__(self, *args, **kwargs):
        super(NetworkDiscovery, self).__init__(*args, **kwargs)
        self.topology_api_app = self
        self.name = "discovery"
        self.link_to_port = {}       # (src_dpid,dst_dpid)->(src_port,dst_port)
        self.paths = {}        
        self.network = nx.DiGraph()

    events = [event.EventSwitchEnter,
              event.EventSwitchLeave, event.EventPortAdd,
              event.EventPortDelete, event.EventPortModify,
              event.EventLinkAdd, event.EventLinkDelete]

    @set_ev_cls(events)
    def get_topology(self, ev):
        """
            Get the topology information and create the network graph.
        """
        raw_switches = get_switch(self.topology_api_app, None)
        self.switches = [switch.dp.id for switch in raw_switches]
        
        raw_links = get_link(self.topology_api_app, None)
        self.create_interior_links(raw_links)
        self.get_network(self.link_to_port.keys())       
        return self.network

    def create_interior_links(self, link_list):
        """
            Create a list of the links and the ports connecting the links
        """
        for link in link_list:
            src = link.src
            dst = link.dst
            self.link_to_port[
                (src.dpid, dst.dpid)] = (src.port_no, dst.port_no)

    def get_network(self, link_list):
        """
            Create the network graph and return it.
        """
        for src in self.switches:
            for dst in self.switches:
                if src == dst:
                    continue
                    #self.network.add_edge(src, dst, weight=0)
                elif (src, dst) in link_list:
                    self.network.add_edge(src, dst, weight=1)
        return self.network
