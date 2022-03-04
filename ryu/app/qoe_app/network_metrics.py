from ryu import cfg
from ryu.base import app_manager
from ryu.base.app_manager import lookup_service_brick
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.topology.switches import Switches
from ryu.topology.switches import LLDPPacket
from ryu.lib import hub
from operator import attrgetter
import networkx as nx
import time
import setting
import copy
import json
CONF = cfg.CONF

class NetworkMetrics(app_manager.RyuApp):
    """
        NetworkMetrics is a module for getting the link delay, bandwidth, and   
        packet loss.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(NetworkMetrics, self).__init__(*args, **kwargs)
        self.name = 'network_metrics'
        self.sending_echo_request_interval = 0.05
        # Get the active object of swicthes and discovery module.
        # So that this module can use their data.
        self.sw_module = lookup_service_brick('switches')
        self.discovery = lookup_service_brick('network_info')
        self.datapaths = {}
        self.echo_latency = {}
        self.free_bandwidth = {}
        self.port_stats = {}
        self.flow_stats = {}
        #self.delete_flows = False
        #self.delete_count = 1000
        #self.initial_transmission = False
        #self.initial_packets = 2000
        self.measure_thread = hub.spawn(self._detector)
    
    """
        Handles the state change and registers the switches to the datapaths
        list.
    """
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if not datapath.id in self.datapaths:
                self.logger.debug('Register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('Unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]

    """
        Metric detecting functon.
        Send echo request and calculate link delay, packet loss, and 
        bandwidth periodically
    """
    def _detector(self):
        while True:
            self._send_echo_request()
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(1)
            self._save_link_delay()
            self._save_link_pl() 
            self._save_link_bw() 
            self._show_link_metrics()
            hub.sleep(setting.METRIC_PERIOD)

    """
        This fucntion sends the flow and port stats requests for each datapath.
    """ 
    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    """
        Function for sending and echo request to calculate link delay.
    """
    def _send_echo_request(self):
        try:
            for datapath in self.datapaths.values():
                parser = datapath.ofproto_parser
                echo_req = parser.OFPEchoRequest(datapath, 
                                                 data=bytes("%.12f"%time.time(), 
                                                            'utf-8'))
                datapath.send_msg(echo_req)
                # Important! Don't send echo request together, Because it will
                # generate a lot of echo reply almost in the same time.
                # which will generate a lot of delay of waiting in queue
                # when processing echo reply in _echo_reply_handler.

                hub.sleep(self.sending_echo_request_interval)
        except:
            print("Echo Request Failed")

    """
        Function that handles the echo replies. The echo latency of the links is
        calculated here.
    """
    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def _echo_reply_handler(self, ev):
        now_timestamp = time.time()
        try:
            latency = now_timestamp - eval(ev.msg.data)
            self.echo_latency[ev.msg.datapath.id] = latency
        except:
            return

    """
        Get link delay.
                            Controller
                            |        |
            src echo latency|        |dst echo latency
                            |        |
                       SwitchA-------SwitchB
                            
                        fwd_delay--->
                            <----reply_delay
    """
    def _get_delay(self, src, dst):
        try:
            fwd_delay = self.discovery.network[src][dst]['lldpdelay']
            reply_delay = self.discovery.network[dst][src]['lldpdelay']
            src_latency = self.echo_latency[src]
            dst_latency = self.echo_latency[dst]
            delay = ((fwd_delay + reply_delay- src_latency - dst_latency)/2)*1000
            return max(delay, 0)
        except:
            return 0

    """
        Saving the lldp delay information to the network graph.
    """
    def _save_lldp_delay(self, src=0, dst=0, lldpdelay=0):
        try:
            self.discovery.network[src][dst]['lldpdelay'] = lldpdelay
        except:
            if self.discovery is None:
                self.discovery = lookup_service_brick('discovery')
            return

    """
        Get the link delay and save it to the network graph object.
    """
    def _save_link_delay(self):
        try:
            for src in self.discovery.network:
                for dst in self.discovery.network[src]:
                    if src == dst:
                        continue
                    delay = self._get_delay(src, dst)
                    self.discovery.network[src][dst]['delay'] = delay - 1
        except:
            if self.discovery is None:
                self.discovery = lookup_service_brick('discovery')
            return
    
    """
        Handles the port stats replies
    """
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        """
            Save port's stats info
            Calculate port's speed and save it.
        """
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        #self.stats['port'][dpid] = body
        for stat in sorted(body, key=attrgetter('port_no')):
            port_no = stat.port_no
            if port_no != ofproto_v1_3.OFPP_LOCAL:
                key = (dpid, port_no)
                value = (stat.tx_bytes, stat.rx_bytes, stat.rx_errors,
                         stat.duration_sec, stat.duration_nsec,
                         stat.tx_packets, stat.rx_packets)
                self._save_stats(self.port_stats, key, value, 5)
    """
        Handles the flow stats replies.
    """
    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        body = ev.msg.body
        datapath = ev.msg.datapath
        dpid = datapath.id
        self.flow_stats.setdefault(dpid, {})
        for stat in sorted([flow for flow in body if flow.priority == 1],
                           key=lambda flow: (flow.match.get('in_port'),
                                             flow.match.get('ipv4_dst'))):
            key = (stat.match['in_port'], stat.instructions[0].actions[0].port)
            value = (stat.packet_count)
            self._save_stats(self.flow_stats[dpid], key, value, 1)
            #self._check_delete_conditions(datapath, value, self.initial_packets)
    
#    """
#        Checks if the conditions for deleting the flow stats are met.
#        This is only used in the flow stats initialization step.
#    """
#    def _check_delete_conditions(self, datapath, value, packet_count):
#        num_of_paths = len(self.discovery.paths)
#        num_of_nodes = len(self.discovery.network.nodes())
#        num_hosts = (num_of_paths*2) - 1 
#        if (value >= packet_count and 
#           (self.delete_count < num_of_paths*num_of_nodes - num_hosts)):
#            ofproto = datapath.ofproto
#            parser = datapath.ofproto_parser
#            match = parser.OFPMatch()
#            inst = []
#            self._delete_flows(datapath, ofproto.OFPTT_ALL, match, inst)
#            self.delete_flows = True
#            self.delete_count += 1
    """
        Deletes all flows for the datapath according to the table_id, match
        and instructions arguments.
    """
    def _delete_flows(self, datapath, table_id, match, instructions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        flow_mod = parser.OFPFlowMod(
                                     datapath=datapath,
                                     cookie=2,
                                     cookie_mask=0xFFFFFFFFFFFFFFFF,
                                     table_id=table_id,
                                     command=ofproto.OFPFC_DELETE,
                                     out_port=ofproto.OFPP_ANY,
                                     out_group=ofproto.OFPG_ANY
                                    )
        datapath.send_msg(flow_mod)

    """
        Loop through all switches and delete the flows for each one.
    """
    def _delete_all_flows(self):
        for dpid in self.datapaths:
            datapath = self.datapaths[dpid]
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match = parser.OFPMatch()
            instructions = []
            self._delete_flows(datapath, ofproto.OFPTT_ALL, match, instructions)
    
    """
        Calculate the link bandwidth and save it to the network graph
    """
    def _save_link_bw(self):
        links = self.discovery.link_to_port
        for link in links:
            src_switch = link[0]
            dst_switch = link[1]
            src_port = links[link][0]
            prev_bytes = 0
            period = setting.METRIC_PERIOD
            if len(self.port_stats) != 0:
                prev_stats = self.port_stats[src_switch, src_port]
                if len(prev_stats) > 1:
                    prev_bytes = prev_stats[-2][0] + prev_stats[-2][1]
                    period =  self._get_period(prev_stats[-1][3], 
                                               prev_stats[-1][4],
                                               prev_stats[-2][3], 
                                               prev_stats[-2][4]) 
                throughput = self._get_throughput(
                    self.port_stats[src_switch, src_port][-1][0] + 
                    self.port_stats[src_switch, src_port][-1][1],
                    prev_bytes, period)
                
                capacity = 500
                available_bw = self._get_free_bw(capacity, throughput)
                if self.discovery.network:
                    self.discovery.network[src_switch][dst_switch]['BW'] = available_bw
   
    """
        Calculate link packet loss and save it the network graph
    """ 
    def _save_link_pl(self):
        links = self.discovery.link_to_port
        for link in links:
            if len(self.flow_stats) != 0:
                src_switch = link[0]
                dst_switch = link[1]
                tx_packets = 0
                rx_packets = 0
                src_port = links[link][0]
                dst_port = links[link][1]
                if len(self.flow_stats[link[0]]) == 0:
                    continue
                for key in self.flow_stats[src_switch]:
                    if key[1] == src_port:
                        tx_packets+= self.flow_stats[src_switch][key][-1]
                for key in self.flow_stats[dst_switch]:
                    if key[0] == dst_port:
                        rx_packets+= self.flow_stats[dst_switch][key][-1]    
                if tx_packets == 0: 
                    pl = 0
                else:
                    pl = (tx_packets - rx_packets)/tx_packets
                if self.discovery.network:
                    self.discovery.network[src_switch][dst_switch]['PL'] = pl*100
                
    """
        A function for saving stats to a given dictionary.
    
        _dict: The dictionary to save the value to.
        key: The key associated with the value
        value: The data to save to the dictionary
        length: The max length of the value list
    """
    def _save_stats(self, _dict, key, value, length):
        if key not in _dict:
            _dict[key] = []
        _dict[key].append(value)

        if len(_dict[key]) > length:
            _dict[key].pop(0)

    """
        Calculate the available bandwidth in Mbps.

        capacity: The maximum bw of the link
        throughput: The current throughput of the link
    """
    def _get_free_bw(self, capacity, throughput):
        return max(capacity/10**3 - throughput * 8/10**6, 0)

    """
        Calculate the throughput in bps
        
        now: Current number of bytes
        pre: Previous number of bytes
        period: The period of time between the current and previous bytes.
    """
    def _get_throughput(self, now, pre, period):
        if period:
            return (now - pre) / (period)
        else:
            return 0

    """
        calculates the time 
    """ 
    def _get_time(self, sec, nsec):
        return sec + nsec / (10 ** 9)

    """
        Calculates the period between two times.
        
        n_sec: Current time in seconds
        n_nsec: Time in nanoseconds since n_sec (n_sec + n_nsec = Current time)
        p_sec: Previous time in seconds
        p_nsec: Time in nanoseconds since p_sec (p_sec + p_nsec = Previous time)
    """
    def _get_period(self, n_sec, n_nsec, p_sec, p_nsec):
        period = self._get_time(n_sec, n_nsec) - self._get_time(p_sec, p_nsec)
        return max(period, 0) 

    """
        Get the metrics for the links along the given path.
    """
    def get_path_metrics(self, path):
        """  example path : [h1, 1, 2, 4, 5, h2]""" 
        metrics = []
        path_bw = []
        path_pl = []
        path_delay = []
        index = 1
        # Create a copy of the path as to not alter the original path.
        route = copy.copy(path)
        # Remove the hosts from the path list.
        route.pop(0)
        route.pop(-1)
        if len(self.discovery.network) == 0:
            return
        for switch in route:
            if switch == route[-1]:
                break
            link_bw = self.discovery.network[switch][route[index]]['BW']
            link_pl = self.discovery.network[switch][route[index]]['PL']
            link_delay = self.discovery.network[switch][route[index]]['delay']
            path_bw.append(link_bw)
            path_pl.append(link_pl)
            path_delay.append(link_delay)
            index+=1
        metrics = metrics + path_bw + path_delay + path_pl
        return metrics

    """
        Handles the incoming packets.
    """
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        try:
            # Parsing LLDP packet and get the delay of link.
            src_dpid, src_port_no = LLDPPacket.lldp_parse(msg.data)
            dpid = msg.datapath.id
            if self.sw_module is None:
                self.sw_module = lookup_service_brick('switches')

            for port in self.sw_module.ports.keys():
                if src_dpid == port.dpid and src_port_no == port.port_no:
                    delay = self.sw_module.ports[port].delay
                    self._save_lldp_delay(src=src_dpid, dst=dpid,
                                          lldpdelay=delay)
        except LLDPPacket.LLDPUnknownFormat as e:
            return

    """
        Display the link metrics on the terminal.
    """
    def _show_link_metrics(self):
        if setting.TOSHOW and self.discovery is not None:
            self.logger.info("\nsrc   dst      Packet loss (%)"
                             "  Delay (ms)  Bandwidth (Mbps)")
            self.logger.info("--------------------------------"
                             "------------------------------")
            for src in self.discovery.network:
                for dst in self.discovery.network[src]:
                    if src == dst:
                        pass
                    else:
                        if 'PL' in self.discovery.network[src][dst]:
                            pl = self.discovery.network[src][dst]['PL']
                            delay = self.discovery.network[src][dst]['delay']
                            bw = self.discovery.network[src][dst]['BW']
                            if isinstance(src, str) or isinstance(dst, str):
                                continue
                            self.logger.info(" %s <-> %s : \t%.5f \t%.5f \t%.5f"
                                             %(src, dst, pl, delay, bw))
