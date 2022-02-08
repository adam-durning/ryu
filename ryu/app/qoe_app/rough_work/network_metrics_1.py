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
        self.name = 'networkmetrics'
        self.sending_echo_request_interval = 0.05
        # Get the active object of swicthes and discovery module.
        # So that this module can use their data.
        self.sw_module = lookup_service_brick('switches')
        self.discovery = lookup_service_brick('discovery')

        self.datapaths = {}
        self.echo_latency = {}
        #self.port_features = {}
        self.free_bandwidth = {}
        self.port_stats = {}
        self.flow_stats = {}
        self.measure_thread = hub.spawn(self._detector)

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

    def _detector(self):
        """
            Metric detecting functon.
            Send echo request and calculate link delay, packet loss, and 
            bandwidth periodically
        """
        while True:
            self._send_echo_request()
            #self.create_path_delay()
            for dp in self.datapaths.values():
                #self.port_features.setdefault(dp.id, {})
                self._request_stats(dp)
            
            hub.sleep(setting.DELAY_DETECTING_PERIOD)
            self._save_link_delay()
            self._save_link_pl() 
            self._save_link_bw() 
            self.show_metrics()
 
    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        #req = parser.OFPPortDescStatsRequest(datapath, 0)
        #datapath.send_msg(req)

        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    def _send_echo_request(self):
        """
            Seng echo request msg to datapath.
        """
        for datapath in self.datapaths.values():
            parser = datapath.ofproto_parser
            echo_req = parser.OFPEchoRequest(datapath, 
                                             data=bytes("%.12f"%time.time(), 
                                                        'utf-8'))
            datapath.send_msg(echo_req)
            # Important! Don't send echo request together, Because it will
            # generate a lot of echo reply almost in the same time.
            # which will generate a lot of delay of waiting in queue
            # when processing echo reply in echo_reply_handler.

            hub.sleep(self.sending_echo_request_interval)

    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        """
            Handle the echo reply msg, and get the latency of link.
        """
        now_timestamp = time.time()
        try:
            latency = now_timestamp - eval(ev.msg.data)
            self.echo_latency[ev.msg.datapath.id] = latency
        except:
            return

    def get_delay(self, src, dst):
        """
            Get link delay.
                        Controller
                        |        |
        src echo latency|        |dst echo latency
                        |        |
                   SwitchA-------SwitchB
                        
                    fwd_delay--->
                        <----reply_delay
            delay = (forward delay + reply delay - src datapath's echo latency
        """
        try:
            fwd_delay = self.discovery.network[src][dst]['lldpdelay']
            re_delay = self.discovery.network[dst][src]['lldpdelay']
            src_latency = self.echo_latency[src]
            dst_latency = self.echo_latency[dst]
            delay = ((fwd_delay + re_delay - src_latency - dst_latency)/2 )* 1000
            return max(delay, 0)
        except:
            return float('inf')

    def _save_lldp_delay(self, src=0, dst=0, lldpdelay=0):
        try:
            self.discovery.network[src][dst]['lldpdelay'] = lldpdelay
        except:
            if self.discovery is None:
                self.discovery = lookup_service_brick('discovery')
            return

    def _save_link_delay(self):
        """
            Create link delay data, and save it into graph object.
        """
        try:
            for src in self.discovery.network:
                for dst in self.discovery.network[src]:
                    if src == dst:
                        continue
                    delay = self.get_delay(src, dst)
                    self.discovery.network[src][dst]['delay'] = delay
        except:
            if self.discovery is None:
                self.discovery = lookup_service_brick('discovery')
            return



#    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
#    def port_desc_stats_reply_handler(self, ev):
#        """
#            Save port description info.
#        """
#        msg = ev.msg
#        dpid = msg.datapath.id
#        ofproto = msg.datapath.ofproto
#
#        config_dict = {ofproto.OFPPC_PORT_DOWN: "Down",
#                       ofproto.OFPPC_NO_RECV: "No Recv",
#                       ofproto.OFPPC_NO_FWD: "No Farward",
#                       ofproto.OFPPC_NO_PACKET_IN: "No Packet-in"}
#
#        state_dict = {ofproto.OFPPS_LINK_DOWN: "Down",
#                      ofproto.OFPPS_BLOCKED: "Blocked",
#                      ofproto.OFPPS_LIVE: "Live"}
#
#
#        ports = []
#        for p in ev.msg.body:
#            ports.append('port_no=%d hw_addr=%s name=%s config=0x%08x '
#                         'state=0x%08x curr=0x%08x advertised=0x%08x '
#                         'supported=0x%08x peer=0x%08x curr_speed=%d '
#                         'max_speed=%d' %
#                         (p.port_no, p.hw_addr,
#                          p.name, p.config,
#                          p.state, p.curr, p.advertised,
#                          p.supported, p.peer, p.curr_speed,
#                          p.max_speed))
#            if p.config in config_dict:
#                config = config_dict[p.config]
#            else:
#                config = "up"
#
#            if p.state in state_dict:
#                state = state_dict[p.state]
#            else:
#                state = "up"
#
#            port_feature = (config, state, p.curr_speed)
#            self.port_features[dpid][p.port_no] = port_feature

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
                         stat.duration_sec, stat.duration_nsec, stat.tx_packets, stat.rx_packets)
                self._save_stats(self.port_stats, key, value, 5)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        self.flow_stats.setdefault(dpid, {})
        #self.outward_flow_stats.setdefault(dpid, {})
        for stat in sorted([flow for flow in body if flow.priority == 1],
                           key=lambda flow: (flow.match.get('in_port'),
                                             flow.match.get('ipv4_dst'))):
            key = (stat.match['in_port'], stat.instructions[0].actions[0].port)
            value = (stat.packet_count)
            self._save_stats(self.flow_stats[dpid], key, value, 1)
    
    def _save_link_bw(self):
        self.logger.info('########## Bandwidth ##########')
        links = self.discovery.link_to_port
        for link in links:
            src_switch = link[0]
            dst_switch = link[1]
            src_port = links[link][0]
            dst_port = links[link][1]
            prev = 0
            period = setting.DELAY_DETECTING_PERIOD
            if len(self.port_stats) != 0:
                tmp = self.port_stats[src_switch, src_port]
                if len(tmp) > 1:
                    prev = tmp[-2][0] + tmp[-2][1]
                    period =  self._get_period(tmp[-1][3], tmp[-1][4],
                                              tmp[-2][3], tmp[-2][4]) 
                speed = self._get_speed(
                    self.port_stats[src_switch, src_port][-1][0] + 
                    self.port_stats[src_switch, src_port][-1][1],
                    prev, period)
                
                capacity = 500000
                self.discovery.network[src_switch][dst_switch]['BW'] = self._get_free_bw(capacity, 
                                                                                            speed)
                self.logger.info(' Link %s, BW = %s' % (str(link),
                                        str(self.discovery.network[src_switch][dst_switch]['BW'])))
    
    def _save_link_pl(self):
        links = self.discovery.link_to_port
        self.logger.info("########## Packet Loss ##########")
        for link in links:
            self.logger.info(len(self.flow_stats))
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
                if tx_packets == 0: continue
                self.discovery.network[src_switch][dst_switch]['PL'] = (tx_packets - rx_packets)/tx_packets
    
    def _save_link_pl_port(self):
        links = self.discovery.link_to_port
        self.logger.info("########## Packet Loss ##########")
        for link in links:
            if len(self.port_stats) != 0:
                src_port = links[link][0]
                dst_port = links[link][1]
                if (len(self.port_stats[link[0], src_port][-1]) == 0 and 
                    len(self.port_stats[link[1], dst_port][-1]) == 0):
                    continue
                self.logger.info("Link is: (%s,%s) - > (%s, %s)" % (str(link[0]), 
                                  str(links[link][0]), str(link[1]), str(links[link][1])))
                tx_packets = self.port_stats[link[0], src_port][-1][5]
                rx_packets = self.port_stats[link[1], dst_port][-1][6]
                pl = (tx_packets - rx_packets)/tx_packets
                self.logger.info('tx_packets = ' + str(tx_packets))
                self.logger.info("rx_packets = " + str(rx_packets))
                self.logger.info("packet loss = " + str(pl*100) + '%')
                
    def _save_stats(self, _dict, key, value, length):
        if key not in _dict:
            _dict[key] = []
        _dict[key].append(value)

        if len(_dict[key]) > length:
            _dict[key].pop(0)


    def _get_free_bw(self, capacity, speed):
        # BW:Mbit/s
        return max(capacity/10**3 - speed * 8/10**6, 0)

    def _get_speed(self, now, pre, period):
        if period:
            return (now - pre) / (period)
        else:
            return 0
 
    def _get_time(self, sec, nsec):
        return sec + nsec / (10 ** 9)

    def _get_period(self, n_sec, n_nsec, p_sec, p_nsec):
        return self._get_time(n_sec, n_nsec) - self._get_time(p_sec, p_nsec)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
            Parsing LLDP packet and get the delay of link.
        """
        msg = ev.msg
        try:
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

    def show_delay_statis(self):
        if setting.TOSHOW and self.discovery is not None:
            self.logger.info("\nsrc   dst      delay (ms)")
            self.logger.info("---------------------------")
            for src in self.discovery.network:
                for dst in self.discovery.network[src]:
                    if src == dst:
                        pass
                    else:
                        delay = self.discovery.network[src][dst]['delay']
                        self.logger.info(" %s <-> %s : \t%.3f" % 
                                        (src, dst, delay))

    def show_metrics(self):
        dictionary = nx.to_dict_of_dicts(self.discovery.network)
        pretty = json.dumps(dictionary, indent=4)
        print(pretty)

    #def create_path_delay(self):
    #    paths = self.awareness.get_paths(1,3)
    #    pathid = 1;
    #    for path in paths:
    #        path_len = len(path)
    #        delay = 0
    #        for (index, switch) in enumerate(path):
    #            if index == path_len-1:
    #                break
    #            else:
    #                delay += self.awareness.network[switch][path[index+1]]['delay']
    #        pathid += 1 
    #        return delay

    #def _save_freebandwidth(self, dpid, port_no, speed):
    #    # Calculate free bandwidth of port and save it.
    #    port_state = self.port_features.get(dpid).get(port_no)
    #    if port_state:
    #        capacity = 500000
    #        curr_bw = self._get_free_bw(capacity, speed)
    #        self.free_bandwidth[dpid].setdefault(port_no, None)
    #        self.free_bandwidth[dpid][port_no] = curr_bw
    #        self.logger.info('('+str(dpid)+','+str(port_no)+') = '+str(curr_bw))
    #    else:
    #        self.logger.info("Fail in getting port state")   
