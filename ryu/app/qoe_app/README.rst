QoE Routing
***********
This is a ryu application that uses a machine learning model to predict the QoE (Quality of Experience) 
score for each path in the network in order to route traffic so that the application's QoE is maximised.

The application uses the following python scripts:

network_info.py
***************
This script gathers information about the network topology whenever a switch or link is added/deleted from
the network. The network topology is stored in a networkx graph object. For more info on networkx, check 
out the documentation here : https://networkx.org/

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

