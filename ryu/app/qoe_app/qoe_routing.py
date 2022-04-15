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
from ryu.controller.handler import (CONFIG_DISPATCHER , MAIN_DISPATCHER,
                                    DEAD_DISPATCHER)
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.lib.packet import packet, arp, ipv6, ipv4, icmp
from ryu.lib.packet import ethernet, ether_types
from ryu.topology import event
from ryu.topology.switches import Switches
from copy import copy
import networkx as nx
import _pickle as pickle
import numpy as np
import openpyxl as op
import pandas as pd
import network_info, network_metrics
import time
import csv
import gzip

class QoeForwarding(app_manager.RyuApp):
    """
       QoeForwarding is a Ryu app for forwarding flows in terms of predicted 
       QoE results from ML models.

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
        self.qoe_metrics = []
        self.exp_num = 1
        self.bw_df = pd.read_excel('topo_info/bw_info.xlsx')
        # The following variables are used for the initial transmission to 
        # initialize the flow stats
        self.initialize_flow_stats = True
        self.hosts = []
        self.selected_path = []
        self.path_num = 0
        self.delete_flows = False
        self.loaded_models = False
        self.models = {}

    """
        This function is used in intializing the flow stats that are used for
        calculating PL. The function updates the path number to transmit 
        packets on and updates the flag used to indicate the initalizing 
        period to False when the initial transmission over all paths is 
        finished.
    """
    def _change_paths(self):
        self.network_metrics._delete_all_flows()
        self.path_num += 1
        self.paths.clear()
        print("########## Changing Paths ##########")
        # If the path number is the same as the number of paths, then we have 
        # transmitted over all paths and this inialization step is over.
        if self.path_num == len(self.network_info.paths):
            print("########## Initialize Period Over ##########")
            self.initialize_flow_stats = False

    """
        State change handler that registers switches as they connect to the
        controller.
    """
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if not self.loaded_models:
                two_link_model = self.load_model('models/2links_rf_model.sav')
                three_link_model = self.load_model('models/3links_rf_model.sav')
                four_link_model = self.load_model('models/4links_rf_model.sav')
                self.models['2 link model'] = two_link_model
                self.models['3 link model'] = three_link_model
                self.models['4 link model'] = four_link_model
                self.loaded_models = True
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
            # if all switches in the topology have been registered then read 
            # in the BW information.
            # Change the integer (8) to the total number of switches in your 
            # topology
            if len(self.datapaths) == 8:
                self.read_in_bw_info()
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]
                if not self.datapaths:
                    filename = './data/qoe_metrics.csv'
                    self.list_to_csv(self.qoe_metrics, filename)
                    self.reset()
    
    """
        A function that saves a list of lists to a csv file.
    """
    def list_to_csv(self, list_, filename):
        with open(filename, 'a') as f:
            writer = csv.writer(f)
            writer.writerow(['Experiment %i' % self.exp_num])
            for row in list_:
                writer.writerow(row)
            writer.writerow('')

    """
        A funciton for reseting some of the parameters when a network 
        disconnects from the controller.
    """
    def reset(self):
        self.initialize_flow_stats = True
        self.path_num = 0
        self.exp_num += 1
        self.qoe_metrics.clear()
        self.network_metrics._delete_all_flows()
        self.network_info.clear_graph()
        self.paths.clear()
        

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
        actions: The openflow actions associated with the instructions for the
                 flow.
        cookie: The cookie id.
        cookie_mask: The cookie mask
    """
    def add_flow(self, datapath, priority, match,
                 actions, cookie, cookie_mask):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions (
                ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, 
                                priority=priority,
                                cookie=cookie,
                                cookie_mask=cookie_mask,
                                match = match, 
                                instructions= inst, 
                                flags=ofproto.OFPFF_SEND_FLOW_REM,)
        datapath.send_msg(mod)

    """
        Function for handling when a flow is removed. Currently only prints 
        'Flow Removed' to the terminal.
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
        When a link is added or removed from the network, update the topology
        information.
    """ 
    events = [event.EventLinkAdd, event.EventLinkDelete]
    @set_ev_cls(events)
    def get_topology(self, ev):
        self.network = self.network_info.get_topo(ev)
    
    """
        When a host is added to the network then add the host information to 
        the topology graph.
    """
    @set_ev_cls(event.EventHostAdd)
    def host_added(self, ev):
        self.network_info.add_host(ev)

    """
        Reading in the link BW information for the network.
    """
    def read_in_bw_info(self):
        bw_dict = {}
        links = list(self.bw_df.keys())
        for link in links:
            src, dst = (int(el) for el in link.split('-'))
            if src not in bw_dict:
                bw_dict[src] = {}
            bw_dict[src][dst] = self.bw_df[link].iloc[[self.exp_num-1]][0]*1000
            if dst not in bw_dict:
                bw_dict[dst] = {}
            bw_dict[dst][src] = self.bw_df[link].iloc[[self.exp_num-1]][0]*1000
        self.network_metrics.set_capacity(bw_dict)

    """
        Loading the ML model.

        model_name: The name of the model to be loaded.
        
        return: model: The object of the loaded model.
    """ 
    def load_model(self, model_name): 
        with gzip.open(model_name, 'rb') as f:
            print("Loading ML model")
            p = pickle.Unpickler(f)
            model = p.load()  
        return model

    """
        This function is used to select the path according to the QoE scores 
        predicted by the ML model.

        src: The source of the packet
        dst: The destination of the packet
        graph: The graph object containing the network topology information.

        Returns the path with the best QoE score.
    """
    def select_path(self, src, dst, graph):
        qoe_list = []
        link_metrics = {}
        self.graph = graph
        self.path_list = list(nx.shortest_simple_paths(graph, source=src,
                                                       target=dst))            
        if self.initialize_flow_stats:
            if self.path_num == 0:
                return self.path_list[0]
            elif self.path_num == 1:
                return self.path_list[1]
            else:
                return self.path_list[2]
                    
        for (path_num, path) in enumerate(self.path_list):
            link_metrics[path_num] = \
                            self.network_metrics.get_path_metrics(path)
            path_len = len(path)
            # The structure of the path is something like 
            # [host 1, switch 1, switch 2, ..., switch n, host 2]
            # The number of switches in a path will be the length of the 
            # path minus the two hosts
            # The number of links in a path will always be one less that 
            # the number of switches, therefore :
            num_links = path_len - 3 
            qoe_list.append(self.predict_score(link_metrics, path_num, 
                                               num_links))
            if src == "00:00:00:00:00:01":
                self.qoe_metrics.append(['%i Link Path' % num_links] + \
                    copy(link_metrics[path_num]) + [qoe_list[-1]])
        qoe_index = qoe_list.index(max(qoe_list)) 
        self.selected_path = self.path_list[qoe_index]
        print("The selected path is %s" % str(qoe_list.index(max(qoe_list))+1))
        return self.selected_path

    def predict_score(self, link_metrics, path_num, num_links):
        metrics = np.array(link_metrics[path_num])
        model = self.models['%i link model' % num_links]
        qoe_score = model.predict([metrics])
        print("QoE score for %i link path is %s" % (num_links, str(qoe_score)))
        return qoe_score

    """
        This funcion gets the output port for the packet to be transmitted on.
        
        datapath: The datapath object of the switch that has received the 
                  packet.
        src: The source of the packet.
        dst; The destination of the packet.
        in_port: The port that the switch received the packet from.

        Returns the output port for the packet to be transmitted on according 
        to the selected path based of the best QoE score.
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
        # If the initialize_flow_stats flag is true then we route the traffic
        # according to the current path
        # number. This is only used for initializing the PL metric which is 
        # calculated using flow stats.
        if(self.initialize_flow_stats):
            if '00:00:00:00:00:01' not in self.network_info.network:
                self.network_info.add_host(0)
            pkt = packet.Packet(ev.msg.data)
            eth = pkt.get_protocols( ethernet.ethernet)[0]
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if isinstance(ip_pkt, ipv4.ipv4):
                if not self.network_info.paths:
                    self.network_info._get_paths()
                self._initial_transmission(ev)
        # Otherwise route the traffic using the QoE strategy.
        else:
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
                    self.add_flow(datapath, 1, match, actions, 2, 
                                  0xFFFFFFFFFFFFFFFF)
                data = None
                if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                    data = msg.data

                out = parser.OFPPacketOut(datapath=datapath, 
                                          buffer_id=msg.buffer_id,
                                          in_port = in_port, 
                                          actions=actions, data=data)
                datapath.send_msg(out)

    """
        This function is used for transmitting the packets when intializing the
        flow stats and PL metric.
    """
    def _initial_transmission(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        icmp_pkt = pkt.get_protocols(icmp.icmp)
        dst = eth.dst
        src = eth.src
        if str(dst) == "00:00:00:00:00:03" or str(src) == "00:00:00:00:00:03":
            self._change_paths()
            return
        dpid = datapath.id
        out_port = self.get_out_port(datapath, src, dst, in_port)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            print("Adding new flow")
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions, 2, 0xFFFFFFFFFFFFFFFF)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, 
                                  buffer_id=msg.buffer_id,
                                  in_port = in_port, 
                                  actions=actions, 
                                  data=data)
        datapath.send_msg(out)


    """
        This function gets the path to transmit on according to the current 
        path number. Used in intialization step.
    """    
    def _get_path(self, path_num, src, dst):
        paths = self.network_info.paths
        if src == paths[path_num][0]:
            return paths[path_num]
        elif dst == paths[path_num][0]:
            paths[path_num].reverse()
            return paths[path_num]
        else:
            return paths[path_num]
