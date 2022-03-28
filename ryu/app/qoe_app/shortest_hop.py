#-------------------------------------------------------------------------------
# Name:        QoE Routing
# Purpose:     Routes traffic using a QoE machine learning model
#
# Author:      Adam Durning & Lei Wang
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
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, arp, ipv6, ipv4, icmp
from ryu.lib.packet import ethernet, ether_types
from ryu.topology import event
from ryu.topology.switches import Switches
import networkx as nx
import signal
import network_info, network_metrics
from itertools import islice
import pickle
import pandas
import numpy as np
import time
import openpyxl as op
import pandas
from collections import defaultdict
from ryu.lib import hub
import csv
import copy

class QoeForwarding(app_manager.RyuApp):
    """
       QoeForwarding is a Ryu app for forwarding flows in terms of predicted QoE results from ML models.

    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
        "network_info": network_info.NetworkInfo,
        "network_metrics": network_metrics.NetworkMetrics,
      }

    def __init__(self, *args, **kwargs):
        super(QoeForwarding, self).__init__(*args, **kwargs)
        self.name = "qoe_forwarding"
        self.mac_to_port = {}
        self.network = nx.DiGraph()
        self.graph = {}
        self.topology_api_app = self
        self.paths = {}
        self.network_info= kwargs["network_info"]
        self.network = self.network_info.network
        self.network_metrics = kwargs["network_metrics"]
        self.path_list = []
        self.datapaths = {}
        ## The following variables are used for the initial transmission to calculate pl ###########
        self.initialize_flow_stats = False
        self.hosts = []
        self.selected_path = []
        self.path_num = 0
        self.delete_flows = False
        self.sample_metrics = []
        ############################################################################################

    """
        State change handler that registers switches as they connect to the controller.
    """
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
                if not self.datapaths:
                    self.network_metrics._delete_all_flows()
                    self.network_info.clear_graph()
    """
        Adds the table-miss flows to the switches.
    """
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

    """
        This function is used to add flows to switches.

        datatpath: The datapath object to add the flow for.
        priority: The priority level for the flow.
        match: The openflow match for the flow.
        actions: The openflow actions associated with the instructions for the flow.
        cookie: The cookie id.
        cookie_mask: The cookie mask
    """
    def add_flow(self, datapath, priority, match, actions, cookie, cookie_mask):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions (ofproto.OFPIT_APPLY_ACTIONS,
                                              actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority= priority, cookie=cookie,
                                cookie_mask=cookie_mask,
                                match = match, instructions= inst, flags=ofproto.OFPFF_SEND_FLOW_REM,)
        datapath.send_msg(mod)

    """
        Function for handling when a flow is removed. Currently only prints 'Flow Removed' to 
        the terminal.
    """ 
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

    """
        When a link is added or removed from the network, update the topology information.
    """ 
    events = [event.EventLinkAdd, event.EventLinkDelete]
    @set_ev_cls(events)
    def get_topology(self, ev):
        self.network = self.network_info.get_topo(ev)
    
    """
        When a host is added to the network then add the host information to the topology graph.
    """
    @set_ev_cls(event.EventHostAdd)
    def host_added(self, ev):
        self.network_info.add_host(ev)
 
    """
        This function is used to select the path according to the QoE scores predicted by the ML model.

        src: The source of the packet
        dst: The destination of the packet
        graph: The graph object containing the network topology information.

        Returns the path with the best QoE score.
    """
    def select_path(self, src, dst, graph):
        self.graph  =  graph
        self.shortest_path =  list(islice(nx.shortest_simple_paths(graph, source=src,
                                             target=dst), 1))
        return self.shortest_path[0]

    """
        This funcion gets the output port for the packet to be transmitted on.
        
        datapath: The datapath object of the switch that has received the packet.
        src: The source of the packet.
        dst; The destination of the packet.
        in_port: The port that the switch received the packet from.

        Returns the output port for the packet to be transmitted on according to the
        selected path based of the best QoE score.
    """    
    def get_out_port(self, datapath, src, dst, in_port):
        dpid = datapath.id
        self.paths.setdefault(src, {})
        if dst in self.network:
            # Checking if the path has already been selected.
            if dst not in self.paths[src]:
                path = self.select_path(src, dst, self.network)
                self.paths[src][dst] = path
            path = self.paths[src][dst]
            next_hop = path[path.index(dpid)+1]
            out_port= self.network[dpid][next_hop]['port']
        else:
            out_port = datapath.ofproto.OFPP_FLOOD

        return out_port

    """
        This function handles when a packet is received by a switch.
    """
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg= ev.msg
        datapath = msg.datapath
        ofproto= datapath.ofproto
        parser = datapath.ofproto_parser

        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols( ethernet.ethernet)[0]
        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if isinstance(ip_pkt, ipv4.ipv4):
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
