from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import CPULimitedHost
from mininet.link import TCLink
from mininet.util import dumpNodeConnections
from mininet.log import setLogLevel
from mininet.node import RemoteController
from mininet.cli import CLI
import re
import time
import os
import random
import csv
from io import open

REMOTE_CONTROLLER_IP = "192.168.56.101"#"192.168.56.105"
#"192.168.56.101"


class MultipathTopo(Topo):
    "Single switch connected to n hosts."

    def __init__(self, num, two_link, three_link, four_link):
        Topo.__init__(self)

        Host1 = self.addHost('h1', mac="00:00:00:00:00:01")
        Host2 = self.addHost('h2', mac="00:00:00:00:00:02")
        Host3 = self.addHost('h3', mac="00:00:00:00:00:03")

      
        Switch1 = self.addSwitch('s1', protocols='OpenFlow13')
        Switch2 = self.addSwitch('s2', protocols='OpenFlow13')
        Switch3 = self.addSwitch('s3', protocols='OpenFlow13')
        Switch4 = self.addSwitch('s4', protocols='OpenFlow13')
        Switch5 = self.addSwitch('s5', protocols='OpenFlow13')
        Switch6 = self.addSwitch('s6', protocols='OpenFlow13')
        Switch7 = self.addSwitch('s7', protocols='OpenFlow13')
        Switch8 = self.addSwitch('s8', protocols='OpenFlow13')

        self.addLink(Host1, Switch1)
        self.addLink(Host2, Switch3)
        self.addLink(Host3, Switch7)

        topo_metric1 = two_link
        topo_metric2 = three_link
        topo_metric3 = four_link
      
        self.addLink(Switch1, Switch2, bw=topo_metric1[0], delay=str(topo_metric1[1])+'ms', loss=topo_metric1[2])
        self.addLink(Switch2, Switch3, bw=topo_metric1[3], delay=str(topo_metric1[4])+'ms', loss=topo_metric1[5])
    
        self.addLink(Switch1, Switch4, bw=topo_metric2[0], delay=str(topo_metric2[1])+'ms', loss=topo_metric2[2])
        self.addLink(Switch4, Switch5, bw=topo_metric2[3], delay=str(topo_metric2[4])+'ms', loss=topo_metric2[5])
        self.addLink(Switch5, Switch3, bw=topo_metric2[6], delay=str(topo_metric2[7])+'ms', loss=topo_metric2[8])

        self.addLink(Switch1, Switch6, bw=topo_metric3[0], delay=str(topo_metric3[1])+'ms', loss=topo_metric3[2])
        self.addLink(Switch6, Switch7, bw=topo_metric3[3], delay=str(topo_metric3[4])+'ms', loss=topo_metric3[5])
        self.addLink(Switch7, Switch8, bw=topo_metric3[6], delay=str(topo_metric3[7])+'ms', loss=topo_metric3[8])
        self.addLink(Switch8, Switch3, bw=topo_metric3[9], delay=str(topo_metric3[10])+'ms', loss=topo_metric3[11])

def video_trans(h1, h2, num):
    print('===============----------------Starting Video Streaming---------------------=================')
    for i in range(2,5):
        h2.cmd('vlc rtp://@:5004 --sout "#std{access=file,mux=ts,dst=./output/thesis/video%i_%i_link.ts}" --run-time 25 vlc://quit &' % (num, i))
        h1.cmd('vlc -vvv ./source/highway600.ts --sout "#rtp{mux=ts,dst=10.0.0.2,port=5004}"  --run-time 25 vlc://quit')
        time.sleep(1)
        if i == 4:
            break
        command = ("ping 10.0.0.3 -c 1 -f")
        print("#################### Sending change path signal ####################")
        print(command)
        h1.cmd(command)


def initial_trans(h1, h2, bandwidths):
    time.sleep(2)
    print('===============-----Initializing Packet Loss-----=================')
    num_packets = 1000
    bytes_pp = 64
    num_bytes = bytes_pp*num_packets
    num_bits = num_bytes*8
    for i in range(3):
        print("#################### Adding Flows ####################")
        h1.cmd("ping 10.0.0.2 -c 3 -f")
        bw = round(bandwidths[i]*0.6, 2)
        t_sec = round(num_bits/(bw*1000000), 1)
        #command = ("iperf -s -b %sM -u -P 1 &" % bw)
        command = ("iperf -s -f M -u -P 1 &")
        print("#################### Starting iperf server ####################")
        print(command)
        h2.cmd(command)
        #time.sleep(2)
        command = ("iperf -c 10.0.0.2 -b %sM -u -t %s -l %s" % (bw, str(t_sec), str(bytes_pp)))
        print("#################### Starting iperf client ####################")
        print(command)
        t0 = time.time()
        h1.cmd(command)
        t1 = time.time()
        time.sleep(((t1-t0)-t_sec)*5)
        command = ("ping 10.0.0.3 -c 1 -f")
        print("#################### Sending change path signal ####################")
        print(command)
        h1.cmd(command)
        #time.sleep(2)

#if __name__ == '__main__':
#    num = 1
def run_experiment(num, two_link, three_link, four_link):
    # Tell mininet to print useful information
    setLogLevel('info')
    print("#################### Experiment number %d ####################" % num)
  #  simpleTest()
    topo = MultipathTopo(num, two_link, three_link, four_link)
    net = Mininet(topo=topo,
                  controller=None,
                  link=TCLink,
                  autoStaticArp=True)
    net.addController("c0",
                      controller=RemoteController,
                      ip=REMOTE_CONTROLLER_IP,
                      port=6633)
    net.start()
    if num == 1:
        time.sleep(15)
    h1, h2 = net.get('h1', 'h2')
    bw1 = min([two_link[0], two_link[3]])
    bw2 = min([three_link[0], three_link[3], three_link[6]])
    bw3 = min([four_link[0], four_link[3], four_link[6], four_link[9]])
    initial_trans(h1, h2, [bw1, bw2, bw3])
    CLI(net)
    #time.sleep(6)
    #video_trans(h1, h2, num)
    net.stop()

