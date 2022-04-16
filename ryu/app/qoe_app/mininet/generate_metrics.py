import csv
import random
import pandas as pd
import os

def generate_metrics():
    metrics_dict = {'2link':[], '3link':[], '4link':[]}
    pl = get_pl(2)
    set_metrics(metrics_dict['2link'], pl)
    pl = get_pl(3)
    set_metrics(metrics_dict['3link'], pl)
    pl = get_pl(4)
    set_metrics(metrics_dict['4link'], pl)
    return metrics_dict

def get_pl(num_links):
    pl_sum = random.randint(0, 100)/10
    prev_pl = 0
    list_ = []
    for i in range(num_links-1):
        pl = round(random.uniform(0, pl_sum - prev_pl), 2)
        list_.append(pl)
        prev_pl += pl
    list_.append(round(pl_sum - sum(list_), 2))
    return list_

def set_metrics(metrics, pl):
    tot_delay = 400
    link_delay = round(tot_delay/len(pl))
    for i in range(len(pl)):
        if i == 0:
            bw = round(random.uniform(50, 100)/100, 2)
        else:
            bw = round(random.uniform(80, 120)/100, 2)
        metrics.append(bw)
        metrics.append(random.randint(0, link_delay))
        metrics.append(pl[i])

def save_metrics(filepath, metrics, num):
    for key in metrics:
        filename = filepath + key + '_topoinfo.csv'
        with open(filename, 'a') as f:
            writer = csv.writer(f, delimiter=',')
            writer.writerow(metrics[key])

def save_bw_info(filename, metrics, i):

    paths = [['1', '2', '3'], 
             ['1', '4', '5', '3'], 
             ['1', '6', '7', '8', '3']]
    links = []
    for path in paths:
        for idx, switch in enumerate(path):
            if switch == path[-1]:
                continue
            link = switch + '-' + path[idx+1]
            links.append(link)
    bw_2link = [metrics['2link'][0], metrics['2link'][3]]
    bw_3link = [metrics['3link'][0], metrics['3link'][3],
                metrics['3link'][6]]
    bw_4link = [metrics['4link'][0], metrics['4link'][3],
                metrics['4link'][6], metrics['4link'][9]]
    bw_info = bw_2link + bw_3link + bw_4link
    df = pd.DataFrame(columns=links)

        
    for idx, key in enumerate(links):
        df[key] = [bw_info[idx]]
    if os.path.exists(filename):
        with pd.ExcelWriter(filename, 
                            engine='openpyxl', 
                            mode='a', 
                            if_sheet_exists='overlay') as writer:
            df.to_excel(writer, 
                        sheet_name='bw_info', 
                        index=False, 
                        startrow=writer.sheets['bw_info'].max_row, 
                        header=None)
    else:
        writer = pd.ExcelWriter(filename, engine='openpyxl')
        df.to_excel(writer, sheet_name='bw_info', index=False)
        writer.save()
        

if __name__ == '__main__':
    num_simulations = 3
    for i in range(1, num_simulations):
        metrics = generate_metrics()
        filepath = 'topo_info/'
        save_metrics(filepath, metrics, i)
        filename = 'topo_info/bw_info_test.xlsx'
        save_bw_info(filename, metrics, i)
