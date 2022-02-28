from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import CPULimitedHost
from mininet.link import TCLink
from mininet.util import dumpNodeConnections
from mininet.log import setLogLevel
from mininet.node import RemoteController
from ping3 import ping
from mininet.cli import CLI
import re
import time
import os
import random
import csv
from io import open

REMOTE_CONTROLLER_IP = "127.0.0.1"



class MultipathTopo(Topo):
    "Single switch connected to n hosts."

    def __init__(self):
        Topo.__init__(self)
        Host1 = self.addHost('h1')
        Host2 = self.addHost('h2')

      
        Switch1 = self.addSwitch('s1', protocols='OpenFlow13')
        Switch2 = self.addSwitch('s2', protocols='OpenFlow13')
        Switch3 = self.addSwitch('s3', protocols='OpenFlow13')
        Switch4 = self.addSwitch('s4', protocols='OpenFlow13')
        Switch5 = self.addSwitch('s5', protocols='OpenFlow13')
        Switch6 = self.addSwitch('s6', protocols='OpenFlow13')
        Switch7 = self.addSwitch('s7', protocols='OpenFlow13')
        Switch8 = self.addSwitch('s8', protocols='OpenFlow13')
      
        topo_metric1 = []
        topo_metric2 = []
        topo_metric3 = []
        for i in range(2):          
            topo_metric1.append(round(random.uniform(2, 10)/10, 2))
            topo_metric1.append(random.randint(0, 600))
            topo_metric1.append(random.randint(0, 50)/10)
        for j in range(3):          
            topo_metric2.append(round(random.uniform(2, 10)/10, 2))
            topo_metric2.append(random.randint(0, 600))
            topo_metric2.append(random.randint(0, 50)/10)
        for k in range(4):          
            topo_metric3.append(round(random.uniform(2, 10)/10, 2))
            topo_metric3.append(random.randint(0, 600))
            topo_metric3.append(random.randint(0, 50)/10)
         


        self.addLink(Host1, Switch1)
        self.addLink(Host2, Switch3)
        self.addLink(Switch1, Switch2, bw=topo_metric1[0], delay=str(topo_metric1[1])+'ms', loss=topo_metric1[2])
        self.addLink(Switch2, Switch3, bw=topo_metric1[3], delay=str(topo_metric1[4])+'ms', loss=topo_metric1[5])
    
        self.addLink(Switch1, Switch4, bw=topo_metric2[0], delay=str(topo_metric2[1])+'ms', loss=topo_metric2[2])
        self.addLink(Switch4, Switch5, bw=topo_metric2[3], delay=str(topo_metric2[4])+'ms', loss=topo_metric2[5])
        self.addLink(Switch5, Switch3, bw=topo_metric2[6], delay=str(topo_metric2[7])+'ms', loss=topo_metric2[8])
        self.addLink(Switch1, Switch6, bw=topo_metric3[0], delay=str(topo_metric3[1])+'ms', loss=topo_metric3[2])
        self.addLink(Switch6, Switch7, bw=topo_metric3[3], delay=str(topo_metric3[4])+'ms', loss=topo_metric3[5])
        self.addLink(Switch7, Switch8, bw=topo_metric3[6], delay=str(topo_metric3[7])+'ms', loss=topo_metric3[8])
        self.addLink(Switch1, Switch8, bw=topo_metric3[9], delay=str(topo_metric3[10])+'ms', loss=topo_metric3[11])

        with open('./data/topoinfo.csv', 'a') as f:
            writer = csv.writer(f, delimiter=',')
            writer.writerow((
            str(topo_metric1[0]), str(topo_metric1[1]), str(topo_metric1[2]), str(topo_metric1[3]),str(topo_metric1[4]), str(topo_metric1[5]),
            str(topo_metric2[0]), str(topo_metric2[1]), str(topo_metric2[2]), str(topo_metric2[3]),str(topo_metric2[4]), str(topo_metric2[5]),str(topo_metric2[6]),str(topo_metric2[7]), str(topo_metric2[8]),
            str(topo_metric3[0]), str(topo_metric3[1]), str(topo_metric3[2]), str(topo_metric3[3]),str(topo_metric3[4]), str(topo_metric3[5]),str(topo_metric3[6]),str(topo_metric3[7]), str(topo_metric3[8]),
            str(topo_metric3[9]), str(topo_metric3[10]), str(topo_metric3[11])              
                            ))



def video_trans(h1, h2):
    print('===============----------------Starting Video Streaming---------------------=================')

    h2.cmd('vlc rtp://@:5004 --sout "#std{access=file,mux=ts,dst=output.ts}" --run-time 25 vlc://quit &')
    h1.cmd('vlc -vvv ./source/highway500.ts --sout "#rtp{mux=ts,dst=10.0.0.2,port=5004}"  --run-time 25 vlc://quit')
    net.stop()
    os.system("cp output.ts ./output/video/received_video.ts")
    os.remove("output.ts")

def voip_trans(h1, h2):
    print('===============----------------Starting VoIP Streaming---------------------=================')
    h1.cmd("tcpdump -i h1-eth0 udp -w /media/sf_shared_w/audiof/outaudio/200414/capturetx.pcap &")
    h2.cmd("tcpdump -i h2-eth0 udp -w /media/sf_shared_w/audiof/outaudio/200414/capturere.pcap &")

    h2.cmd("/home/mininet/sipp-3.6.0/sipp -sn uas -mi 10.0.0.2 &")
    h1.cmd("/home/mininet/sipp-3.6.0/sipp -sf test.xml 10.0.0.2 -mi 10.0.0.1 -m 1 &")




if __name__ == '__main__':
    # Tell mininet to print useful information
    setLogLevel('info')
  #  simpleTest()
    topo = MultipathTopo()
    net = Mininet(topo=topo,
                  controller=None,
                  link=TCLink,
                  autoStaticArp=True)
    net.addController("c0",
                      controller=RemoteController,
                      ip=REMOTE_CONTROLLER_IP,
                      port=6633)
    net.start()
    h1, h2 = net.get('h1', 'h2')
    video_trans(h1, h2)
    # voip transmission is not ready, you can test the video transmission at first 
  #  voip_trans(h1, h2)

    


