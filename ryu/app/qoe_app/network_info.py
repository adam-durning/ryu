from ryu.base import app_manager
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
import networkx as nx
from ryu.topology.api import get_switch, get_link, get_host
from ryu.topology import event, switches
import copy

"""
    A class for getting and maintaining an accurate view of the network topology.
"""
class NetworkInfo(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(NetworkInfo, self).__init__(*args, **kwargs)
        self.name = "network_info"
        self.network = nx.DiGraph()
        self.topology_api_app = self
        self.links = []
        self.link_to_port = {} 
        self.hosts = []
        self.paths = []
        self.h1 = (1,'00:00:00:00:00:01',{'port':1})
        self.h2 = (3,'00:00:00:00:00:02',{'port':1})
        #self.h1_link = []
        #self.h2_link = []
        #self.prev_h1 = ''
        #self.prev_h2 = ''
    
    """
        Gets the topology information and creates the network graph object.
    """
    def get_topo(self, ev):
        switch_list = get_switch(self.topology_api_app, None)
        self.switches = [switch.dp.id for switch in switch_list]
        self.network.add_nodes_from(self.switches)

        link_list = get_link(self.topology_api_app, None)
        self.links = [(link.src.dpid, link.dst.dpid, {'port':link.src.port_no}) for link in link_list]
        self.network.add_edges_from(self.links)
        self.links = [(link.dst.dpid, link.src.dpid, {'port':link.dst.port_no}) for link in link_list]
        self.network.add_edges_from(self.links)

        self.network.add_edges_from([self.h1])
        self.network.add_edges_from([self.h2])
        self.network.add_edge(self.h1[1], self.h1[0])
        self.network.add_edge(self.h2[1], self.h2[0])

        self.create_interior_links(link_list)
        self.initialize_metrics() 
        return self.network

    """
        Adds the host information to the network graph and updates the h1 and h2 parameters that are used
        in the _get_paths function below.
    """
    def add_host(self, ev):
        host_list = get_host(self.topology_api_app, None)
        links = [(host.port.dpid, host.mac, {'port':host.port.port_no}) for host in host_list]
        self.hosts = [host for host in host_list]
        for link in links:
            if link[0] == 1 and link[2]['port'] == 1:# and not self.h1 :
                #if link[1] == self.prev_h1:
                #    continue
                self.h1 = link[1]
                self.h1_link = [link]
                self.network.add_edges_from(self.h1_link)
                self.network.add_edge(link[1], link[0])
            elif link[0] == 3 and link[2]['port'] == 1:# and not self.h2:
                #if link[1] == self.prev_h2:
                #    continue
                self.h2 = link[1]
                self.h2_link = [link]
                self.network.add_edges_from(self.h2_link)
                self.network.add_edge(link[1], link[0])
    """
        Get the paths between the two the hosts from the network graph
    """
    def _get_paths(self):
        try:
            #if self.h1 not in self.network:
            #    self.network.add_edges_from(self.h1_link)
            #    self.network.add_edge(self.h1_link[0][1], self.h1_link[0][0])
            #if self.h2 not in self.network:
            #    self.network.add_edges_from(self.h2_link)
            #    self.network.add_edge(self.h2_link[0][1], self.h2_link[0][0])
            self.paths = list(nx.shortest_simple_paths(self.network, source=self.h1,
                                  target=self.h2))
        except ValueError as e:
                print(e)
    
    """
        Remove a switch from the network graph
    """
    def delete_switch(self, dpid):
        if dpid in self.network.nodes():
            self.network.remove_node(dpid)
        return self.network 

    """
        Clear the network graph
    """
    def clear_graph(self):
        self.network.clear()
        self.links = []
        self.link_to_port = {} 
        self.paths = []
        #self.prev_h1 = copy.copy(self.h1)
        #self.prev_h2 = copy.copy(self.h2)
        #self.h1 = ''
        #self.h2 = ''
        return self.network
 
    """
        Create a list of the links and the ports connecting the links
    """
    def create_interior_links(self, link_list):
        for link in link_list:
            src = link.src
            dst = link.dst
            self.link_to_port[
                (src.dpid, dst.dpid)] = (src.port_no, dst.port_no)

    """
        A function for initializing the metric keys in the network graph
    """
    def initialize_metrics(self):
        keys = set(['BW', 'delay', 'PL'])
        for link in self.network.edges():
            if keys.issubset(self.network[link[0]][link[1]].keys()):                
                continue
            else:
                self.network[link[0]][link[1]]['BW'] = 0   
                self.network[link[0]][link[1]]['PL'] = 0   
                self.network[link[0]][link[1]]['delay'] = 0   
