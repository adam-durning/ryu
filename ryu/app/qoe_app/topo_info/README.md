Topology Information
====================

The files 2link_topoinfo.csv, 3link_topoinfo.csv, and 4link_topoinfo.csv contain the link metric information for the topology below. 
These files are created by [generate_metrics.py](https://github.com/adam-durning/ryu/blob/development_branch/ryu/app/qoe_app/mininet/generate_metrics.py).
Each row contains the metrics for an experiment and are structered as follows: 

      [Link 1 BW, Link 1 Delay, Link 1 PL, Link 2 BW, Link 2 Delay, Link 2 PL, ... ]. 

These files are read by the [qoe_experiments.py](https://github.com/adam-durning/ryu/blob/development_branch/ryu/app/qoe_app/mininet/qoe_experiments.py) 
script and 1 row is selected from each file for each experiment (i.e. the script gets the metrics for all three paths in the topology).


![An image of a network topology with 3 linear paths](../mininet/topology.png "Network Topology")

The bw_info.xlsx file is also generated by the [generate_metrics.py](https://github.com/adam-durning/ryu/blob/development_branch/ryu/app/qoe_app/mininet/generate_metrics.py) 
script and this file is used by the controller so that the controller knows the maximum BW of each link in the network. Maximum Link Bandwidth is usually 
known by the network operator and that is why we do not try to calculate it in this project. The header of the file contains the link source and destination 
switches (e.g. src-dst: 1-2) and each row corresponds to a row in the 3 topoinfo files.