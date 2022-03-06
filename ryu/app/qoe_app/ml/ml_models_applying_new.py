import pickle
import pandas as pd  
from sklearn import preprocessing
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn import preprocessing
from ryu.base import app_manager


class MlModles(app_manager.RyuApp):
    def __init__(self, path):
        super(MlModles, self).__init__(path)
        self.name = "ml_model"
        # training ML models for three path in initialization time
        # but these models are ready in the directory, so just call the ml model based on the given path
        self.path = path
        if self.path == 1:
            dataset_file ='./data/video/topoinfo_2link_hihgways500.csv'
        elif self.path == 2:
            dataset_file ='./data/video/topoinfo_3link_hihgways500.csv'
        else:
            dataset_file ='./data/video/topoinfo_4link_hihgways500.csv'

        


        self.link_metrics=pd.read_csv(dataset_file)   #the dierectory of the database file
        self.link_metrics.data=self.link_metrics.drop('MPSNR', axis=1)
        self.link_metrics.target=self.link_metrics.MPSNR

        min_max_scaler = preprocessing.MinMaxScaler()
        X_minmax = min_max_scaler.fit_transform(self.link_metrics.data)
        X_train, X_test, y_train, y_test = train_test_split(X_minmax, self.link_metrics.target, test_size=0.2, random_state=2)  

        rf_model = RandomForestRegressor(n_estimators = 100, random_state = 0)
        rf_model.fit(X_train,y_train)

        self.filename = 'finalized_model'+ str(self.path) + ".sav"
        pickle.dump(rf_model, open(self.filename, 'wb'))
        
#if __name__ == "__main__":
#    for pathnum in range(1,4):
#        mlmodel_file = MlModles(pathnum).filename   



#y_pred=rf.predict(X_test)

#df = pd.DataFrame({'Actual': y_test, 'Predicted_rf': y_pred})
#df_new= df.sort_values('Actual',ascending =True)
#df_new =df_new.set_index('Actual',drop=False, append=False, inplace=False, verify_integrity=False)
