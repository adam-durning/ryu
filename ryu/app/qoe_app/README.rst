:Authors:
  Adam Durning, Lei Wang
:Version: 1.0 on 18/04/2022

QoE Routing
***********
This is a ryu application that uses a machine learning model to predict the QoE (Quality of Experience) 
score for each path in the network in order to route traffic so that the application's QoE is maximised.
The application used in this project is a Video streaming application using VLC media player to transmit video
data across the network.

Prerequisites
*************
You will need to install the following packages to run the code in this project:

Mininet - instructions are in the mininet directory.

NetworkX - instructions_.

ML models - The machine learning models used in this project can be found here_.

.. _here: https://drive.google.com/drive/folders/18Y67h2MTO8Orkq12O4FGxvl6hxyCdC5U?usp=sharing
.. _instructions: https://networkx.org/documentation/stable/install.html


network_info.py
***************
This script gathers information about the network topology whenever a switch or link is added/deleted from
the network. The network topology is stored in a networkx graph object. For more info on networkx, check 
out the documentation here : https://networkx.org/ .

Note: The latency mechanism used in this module is adapted from the implementation in https://github.com/muzixing/ryu/tree/master/ryu/app/network_awareness .
This mechanism involves editing the topology/switches.py module. The instructions for this are available at the link mentioned.

network_metrics.py
******************
This script collects openflow statistics from the ports and flows in the network. These statistics are used
to calculate network metrics such as link bandwidth, link packet loss, and link delay. These mertrics are
used in the ML model in the qoe_routing.py script in order to predict the QoE score for each path.

qoe_routing.py
**************
This script is the main script for the controller. The other two modules described above are called in this
script to provide the controller with the necessary information it needs for routing the traffic through the 
network. 

