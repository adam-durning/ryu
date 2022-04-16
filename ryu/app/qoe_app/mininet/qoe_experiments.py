import os
import csv
import random
import three_path_topo as test

def read_metrics():
    metrics_dict = {'2link':[], '3link':[], '4link':[]}
    for key in metrics_dict:
        with open('topo_info/%s_topoinfo.csv' % key, 'r') as f:
            reader = csv.reader(f)
            metrics_dict[key].append([])
            for row in reader:
                path_metrics = [float(el) for el in row]
                metrics_dict[key].append(path_metrics)
    return metrics_dict

if __name__ == '__main__':
    metrics = read_metrics()
    for iter_num in range(1, 2):
        two_link = metrics['2link'][iter_num]
        three_link = metrics['3link'][iter_num]
        four_link = metrics['4link'][iter_num]
        test.run_experiment(iter_num, two_link, three_link, four_link)
        os.system("sudo mn -c")

