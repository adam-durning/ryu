#-------------------------------------------------------------------------------
# Name:        module1
# Purpose:
#
# Author:      leiw0
#
# Created:     10/01/2022
# Copyright:   (c) leiw0 2022
# Licence:     <your licence>
#-------------------------------------------------------------------------------
from os import link
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER , MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.controller import dpset
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, arp, ipv6, ipv4
from ryu.lib.packet import ethernet, ether_types
from ryu.topology import event
from ryu.topology.switches import Switches
import networkx as nx
import signal
import network_info, network_metrics
import ml_models_applying
from itertools import islice
import pickle
import pandas
import numpy as np
import time
import openpyxl as op
import pandas
from collections import defaultdict
from ryu.lib import hub

class QoeForwarding(app_manager.RyuApp):
    """
       QoeForwarding is a Ryu app for forwarding flows in terms of predicted QoE results from ML models.

    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        "network_info": network_info.NetworkInfo,
        "network_metrics": network_metrics.NetworkMetrics,
        "ml_model": ml_models_applying.MlModles,
        "dpset": dpset.DPSet
      }

    def __init__(self, *args, **kwargs):
        super(QoeForwarding, self).__init__(*args, **kwargs)
        self.name = "qoe_forwarding"
        self.dpset = kwargs['dpset']
        self.mac_to_port = {}
        self.network = nx.DiGraph()
        self.graph = {}
        self.topology_api_app = self
        self.paths = {}
        self.network_info= kwargs["network_info"]
        self.network = self.network_info.network
        self.ml_model = kwargs["ml_model"]
        self.delay_detector = kwargs["network_metrics"]
        self.shortest_path = []
        self.datapaths = {}
        ## The following variables are used for the initial transmission to calculate pl ###########
        self.initialize_flow_stats = False
        self.hosts = []
        #self.initialize_thread = hub.spawn(self._initialize_flow_stats)
        self.selected_path = []
        self.path_num = 0
        self.packet_count = {}
        ############################################################################################

    def _initialize_flow_stats(self):
        while self.initialize_flow_stats:
            if self.delay_detector.delete_flows is True:
                self.delay_detector._delete_all_flows()
                self.path_num += 1
                print("Changing Paths")
                self.delay_detector.delete_flows = False
                if self.path_num == len(self.network_info.paths):
                    print("Initialize Period Over")
                    self.initialize_flow_stats = False
                    self.delay_detector.delete_count = 1000
            hub.sleep(2)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self,ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        msg = ev.msg
        self.logger.info("switch %s connected", datapath.id)

         # install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]

        self.add_flow(datapath, 0, match, actions, 0, 0)

    def add_flow(self, datapath, priority, match, actions, cookie, cookie_mask):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions (ofproto.OFPIT_APPLY_ACTIONS,
                                              actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority= priority, cookie=cookie,
                                cookie_mask=cookie_mask,
                                match = match, instructions= inst, flags=ofproto.OFPFF_SEND_FLOW_REM,)
        datapath.send_msg(mod)

    def create_flow_mod(self, datapath, priority,
                        table_id, match, instructions):
        """Create OFP flow mod message."""
        ofproto = datapath.ofproto
        flow_mod = datapath.ofproto_parser.OFPFlowMod(datapath, 0, 0, table_id,
                                                      ofproto.OFPFC_ADD, 0, 0,
                                                      priority,
                                                      ofproto.OFPCML_NO_BUFFER,
                                                      ofproto.OFPP_ANY,
                                                      ofproto.OFPG_ANY, 0,
                                                      match, instructions)
        return flow_mod

    def install_table_miss(self, datapath, table_id):
        """Create and install table miss flow entries."""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        empty_match = parser.OFPMatch()
        output = parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                        ofproto.OFPCML_NO_BUFFER)
        write = parser.OFPInstructionActions(ofproto.OFPIT_WRITE_ACTIONS,
                                             [output])
        instructions = [write]
        flow_mod = self.create_flow_mod(datapath, 0, table_id,
                                        empty_match, instructions)
        datapath.send_msg(flow_mod)

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        if msg.reason == ofp.OFPRR_IDLE_TIMEOUT:
            reason = 'IDLE TIMEOUT'
        elif msg.reason == ofp.OFPRR_HARD_TIMEOUT:
            reason = 'HARD TIMEOUT'
        elif msg.reason == ofp.OFPRR_DELETE:
            reason = 'DELETE'
        elif msg.reason == ofp.OFPRR_GROUP_DELETE:
            reason = 'GROUP DELETE'
        else:
            reason = 'unknown'
        print("Flow Removed")
 
    #events = [event.EventSwitchEnter, event.EventSwitchLeave, 
    #          event.EventLinkAdd, event.EventLinkDelete]
    events = [event.EventLinkAdd, event.EventLinkDelete]
    # when the switch enters, or other change of the network happens, network topology information get updated
    @set_ev_cls(events)
    def get_topology(self, ev):
        self.network = self.network_info.get_topo(ev)
        
    @set_ev_cls(event.EventHostAdd)
    def host_added(self, ev):
        self.network_info.add_host(ev)
 
   # call the ml model here 
    def call_ml(self, metrics, model_name): #input metrics are list form
        X_test=np.array(metrics)     #np.array the list metrics
        self.model = pickle.load(open(model_name, 'rb'))  #load the ml model
        self.qoe = self.model.predict([X_test])
        return self.qoe

    def select_path(self, src, dst, graph):
        self.graph  =  graph
        self.shortest_path =  list(islice(nx.shortest_simple_paths(graph, source=src,
                                             target=dst), 1))                           # break the path
        print(self.shortest_path[0])
        return self.shortest_path[0]


    # get outport by shortest hop
    def get_out_port(self, datapath, src, dst, in_port):
        dpid = datapath.id
        #add link between host and access switch
        if src not in self.network:
            self.network.add_node(src)
            self.network.add_edge(dpid, src, port=in_port)
            self.network.add_edge(src, dpid)
        self.paths.setdefault(src, {})

        if dst in self.network:
            if dst not in self.paths[src]:
                path = self.select_path(src, dst, self.network)
                print(path)
                #path = nx.shortest_path(self.network, src, dst)
                self.paths[src][dst] = path

            path = self.paths[src][dst]
            next_hop = path[path.index(dpid)+1]
            #print ("----------------path-----------------:", path)
            out_port= self.network[dpid][next_hop]['port']
        else:
            out_port = datapath.ofproto.OFPP_FLOOD

        return out_port




    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        if(self.initialize_flow_stats):
            pkt = packet.Packet(ev.msg.data)
            eth = pkt.get_protocols( ethernet.ethernet)[0]
            if eth.ethertype in (ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_MPLS,
                                 ether_types.ETH_TYPE_IPV6):
                # ignore lldp, mpls and ipv6 packet
                return
            self._initial_transmission(ev)
            #dpid = ev.msg.datapath.id
            #if (dpid == self.selected_path[-2]) and (self.packet_count[dpid] == 10000):
            #    self.path_num += 1
            #    self.delay_detector._save_link_pl()
            #    if self.path_num == len(self.network_info.paths):
            #        self.initialize_flow_stats = False
        else:
            msg= ev.msg
            datapath = msg.datapath
            ofproto= datapath.ofproto
            parser = datapath.ofproto_parser

            in_port = msg.match["in_port"]
            pkt = packet.Packet(msg.data)
            eth = pkt.get_protocols( ethernet.ethernet)[0]
            if eth.ethertype in (ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_MPLS,
                                 ether_types.ETH_TYPE_IPV6):
                # ignore lldp, mpls and ipv6 packet
                return

            src = eth.src
            dst = eth.dst
            dpid = datapath.id
            self.mac_to_port.setdefault( dpid , {})
            self.mac_to_port[dpid][src] = in_port
 
            out_port = self.get_out_port(datapath, src, dst, in_port)
            actions = [parser.OFPActionOutput(out_port)]

            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
                self.add_flow(datapath, 1, match, actions, 2, 0xFFFFFFFFFFFFFFFF)
            data = None
            if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                data = msg.data

            out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                      in_port = in_port, actions=actions, data=data)
            datapath.send_msg(out)

    def _initial_transmission(self, ev):
        
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP or eth.ethertype == ether_types.ETH_TYPE_IPV6:
            # ignore lldp packet
            return
        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.selected_path = self._get_path(self.path_num, src, dst)
        if dpid not in self.packet_count:
            self.packet_count.setdefault(dpid, 0)
        self.packet_count[dpid] += 1
        next_hop = self.selected_path[self.selected_path.index(dpid)+1]
        out_port = self.network[dpid][next_hop]['port']
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions, 2, 0xFFFFFFFFFFFFFFFF)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port = in_port, actions=actions, data=data)
        datapath.send_msg(out)


        
    def _get_path(self, path_num, src, dst):
        paths = self.network_info.paths
        if src == paths[path_num][0]:
            return paths[path_num]
        elif dst == paths[path_num][0]:
            paths[path_num].reverse()
            return paths[path_num]      # Reversing the list Note: Can also use the following line of code
                                        # to do this[ele for ele in reversed(paths[path_num])]
        else:
            return paths[path_num]
