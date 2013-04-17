import h5py
import numpy as np
from pboost.boost.generic import Boosting, WeakLearner
from scipy import weave

class AdaBoostFast(Boosting):
    def __init__(self, boosting_p):
        """
        
        AdaBoostFast Implementation
        
        Parameters
        ----------

        boosting_p : pboost.boost.process.Process object
            Boosting environment in which this algoritm runs
            
        """
        self.process = boosting_p
        self.pb = boosting_p.pb
        
        self.hypotheses = list()
        self.val_predictions = None
        self.train_predictions = None
        self.test_predictions = None

        """Create empty prediction matrices"""
        if self.process.classifyEN:
            if self.process.isXvalMain:
                train_span = self.pb.train_ind2 - self.pb.train_ind1
                self.train_predictions = np.zeros(
                [train_span,self.pb.rounds],'float32')
                if self.pb.testEN:
                    test_span = self.pb.test_ind2 - self.pb.test_ind1
                    self.test_predictions = np.zeros(
                    [test_span,self.pb.rounds],'float32')
            else:
                if self.pb.isLeader and self.pb.xvalEN:
                    self.val_predictions = np.zeros(
                    [self.process.val_exam_no,self.pb.rounds],'float32')

        """Convert binary labesl to +1/-1 form"""
        self.tl = np.int16(np.copy(self.process.label))
        self.tl[self.process.label == 0] = -1
        

    def run(self, dt, r, rnk, d1, d2, d3, d4, d5, c0, c1, bout):
        """
        
        Run a single round of boosting
        
        
        Parameters
        ----------
        
        dt : numpy float array
            Probability distribution over examples
        
        r : integer
            Round number
        
        rnk : integer
            Rank of the core containing best hyp in its space
            
        d1 : integer
            Index of the best hypothesis
        
        d2 : integer
            The relative index of the example where threshold is placed
            
        d3 : integer
            The actual index of the example where threshold is placed
            
        d4 : integer
            The actual index of the next example in threshold calculation
        c0 : float
            Prediction for values lower than threshold
        
        c1 : float
            Prediction for values larger than threshold
        
        bout : numpy boolean array
            Marker for each example best hyp making a mistake
            
        Returns:
            Updated distribution over examples

        """

                
        """Create a dictionary for the best hypothesis"""
        v = 0.0
        h = {'rnk':rnk,
             'd1':d1,
             'd2':d2,
             'd3':d3,
             'd4':d4,
             'd5':d5,
             'v':v,
             'c0':c0,
             'c1':c1}
        
        self.hypotheses.append(h)
        
        """Update training and validation predictions"""
        if self.process.classifyEN:
            if self.process.isXvalMain:
                pbout = bout[self.pb.train_ind1:self.pb.train_ind2]
                npbout = np.logical_not(pbout)
                s1 = pbout*c0
                s2 = npbout*c1
                self.train_predictions[:,r]=(self.train_predictions[:,r-1]
                                               + s1 + s2)
            else:
                if self.pb.isLeader and self.pb.xvalEN:
                    pbout = bout[self.process.val_indices]
                    npbout = np.logical_not(pbout)
                    s1 = pbout*c0
                    s2 = npbout*c1
                    self.val_predictions[:,r]=(self.val_predictions[:,r-1]
                                                   + s1 + s2)
        
        """Update distribution over the examples"""
        nbout = np.logical_not(bout)
        dt[bout] = dt[bout] * np.exp(-self.tl[bout] * np.float32(c0))
        dt[nbout] = dt[nbout] * np.exp(-self.tl[nbout]  * np.float32(c1))

        return dt / np.sum(dt)
    
    def finalize(self):
        """
        Writes hypotheses and predictions into a file
        """
        
        """Creates a dictionary of rank,rounds pairs"""
        inverse = dict()
        rnk_list = list()
        for r in np.arange(self.pb.rounds):
            h = self.hypotheses[r]
            rnk = h['rnk']
            try:
                inverse[rnk].append(r)
            except KeyError:
                inverse[rnk] = [r,]
                rnk_list.append(rnk)
                pass
        
        """
        For each rank read the hypotheses space to update threshold and test
        predictions
        """
        for rnk in rnk_list:
            model_fp = self.pb.wd + "model_%s_%s.h5" % (self.pb.conf_num,rnk)
            try:
                mf = h5py.File(model_fp,'r')
            except Exception as e:
                print model_fp
                print e
            unsorted_ds = mf["train_unsorted"]
            for r  in inverse[rnk]:
                h = self.hypotheses[r]
                d1 = h['d1']
                d3 = h['d3']
                d4 = h['d4']
                vec = unsorted_ds[d1, :]
                h['v'] = (vec[d3]+vec[d4])/2.0
                self.hypotheses[r] = h
                if self.pb.testEN:
                    tVals = mf["test_unsorted"][d1,self.pb.test_ind1:self.pb.test_ind2]
                    s1 = np.int16([tVals <= h['v']])*h['c0']
                    s2 = np.int16([tVals > h['v']])*h['c1']
                    self.test_predictions[:,r]= s1[0] + s2[0]
            mf.close()
        if self.pb.testEN:
            np.cumsum(self.test_predictions, axis=1, out=self.test_predictions)
        
    def get_hypotheses(self):
        """
        Returns the hypotheses
        """
        return self.hypotheses
    
    def get_val_predictions(self):
        """
        Returns validation predictions
        """
        return self.val_predictions
    
    def get_train_predictions(self):
        """
        Returns training predictions
        """
        return self.train_predictions
    
    def get_test_predictions(self):
        """
        Returns testing predictions
        """
        return self.test_predictions
        

class AdaBoostFastWL(WeakLearner):
    
    def __init__(self, boosting_p):
        """
        
        Decision Stump Implementation compatible with AdaBoostFast
        
        Parameters
        ----------

        boosting_p : pboost.boost.process.Process object
            Boosting environment in which this algoritm runs
            
        """
        self.process = boosting_p
        self.pb = boosting_p.pb

        """Allocate memory for intermediate data matrices"""
        self.__index = self.pb.index_matrix
        self.__err = np.zeros(shape = self.__index.shape,dtype ="float32")
        self.__bout = np.zeros(self.__index.shape[1],dtype="bool")
        self.__dt = np.zeros(shape = self.process.label.shape,dtype ="float32")
        self.__not_label = np.logical_not(self.process.label)
        self.__label = np.logical_not(self.__not_label)
    
    def run(self,dt):
#         dt = np.copy(dt)
        label = self.__label
        index = self.__index
        F = index.shape[0]/4*4
        N = index.shape[1]
        code = """
               float max_e_array[4] __attribute__ ((aligned (16)));
               float min_e_array[4] __attribute__ ((aligned (16)));
               float cmp[4] __attribute__ ((aligned (16)));
               float max_d1_array[4] __attribute__ ((aligned (16)));
               float max_d2_array[4] __attribute__ ((aligned (16)));
               float min_d1_array[4] __attribute__ ((aligned (16)));
               float min_d2_array[4] __attribute__ ((aligned (16)));
               float max_e = -1000.0;
               float min_e = 1000.0;
               int max_d1 = -1;
               int max_d2 = -1;
               int min_d1 = -1;
               int min_d2 = -1;
               
               float e1 = 0.0;
               float e2 = 0.0;
               float err_best = -1.0;
               int d1 = -1;
               int d2 = -1;
               int d3 = -1;
               int d4 = -1;
               float w01_max = 0.0;
               float w00_max = 0.0;
               float w01_bh = 0.0;
               float w00_bh = 0.0;
               float w10_bh = 0.0;
               float w11_bh = 0.0;
               
               for (int i = 0; i<4; i++){
                   max_e_array[i] = -1000.0;
                   min_e_array[i] = 1000.0;
                   cmp[i] = -1.0;
                   max_d1_array[i] = -1;
                   max_d2_array[i] = -1;
                   min_d1_array[i] = -1;
                   min_d2_array[i] = -1;               
               }
               
               float dtp[N];
               for (int j=0; j<N; ++j){
                   if (label(j) == 1){
                       w01_max = w01_max + dt(j);
                       dtp[j] = -dt(j); 
                   }
                   else{
                       dtp[j] = dt(j); 
                       w00_max = w00_max + dt(j);
                   }
               }
               int ii = 0;
               
               __m128 err =  _mm_setzero_ps();
               __m128 a =  _mm_setzero_ps();
               __m128 kk =  _mm_setzero_ps();
               __m128 jj =  _mm_setzero_ps();
               __m128 mask =  _mm_setzero_ps();
               __m128 max_err =  _mm_set1_ps(-1000.0);
               __m128 min_err =  _mm_set1_ps(1000.0);
               __m128 max_d1b =  _mm_set1_ps(-1.0);
               __m128 min_d1b =  _mm_set1_ps(-1.0);
               __m128 max_d2b =  _mm_set1_ps(-1.0);
               __m128 min_d2b =  _mm_set1_ps(-1.0);
               
               for (int k=0; k<F; k+=4 ){
                   err =  _mm_setzero_ps();
                   kk = _mm_set_ps((float)k+3,
                                   (float)k+2,
                                   (float)k+1,
                                   (float)k);
                   for (int j=0; j<N; ++j ){
                       a = _mm_set_ps(dtp[index(k+3,j)],
                                      dtp[index(k+2,j)],
                                      dtp[index(k+1,j)],
                                      dtp[index(k,j)]);
                       jj = _mm_set1_ps((float)j);
                       err = _mm_add_ps(err,a);
                       mask = _mm_cmpgt_ps(err,max_err);
                       int masksum = _mm_movemask_ps( mask );
                       if ( masksum != 0 ){
                           max_err = _mm_xor_ps(max_err,
                                                _mm_and_ps(mask,_mm_xor_ps(err,max_err)));
                           max_d1b = _mm_xor_ps(max_d1b,
                                                _mm_and_ps(mask,_mm_xor_ps(kk,max_d1b)));
                           max_d2b = _mm_xor_ps(max_d2b,
                                                _mm_and_ps(mask,_mm_xor_ps(jj,max_d2b)));
                       }
                       
                       mask = _mm_cmplt_ps(err,min_err);
                       masksum = _mm_movemask_ps( mask );
                       if ( masksum != 0 ){
                           min_err = _mm_xor_ps(min_err,
                                                _mm_and_ps(mask,_mm_xor_ps(err,min_err)));
                           min_d1b = _mm_xor_ps(min_d1b,
                                                _mm_and_ps(mask,_mm_xor_ps(kk,min_d1b)));
                           min_d2b = _mm_xor_ps(min_d2b,
                                                _mm_and_ps(mask,_mm_xor_ps(jj,min_d2b)));
                       }
                       }
               }
               
               _mm_store_ps(max_e_array,max_err);
               _mm_store_ps(max_d1_array,max_d1b);
               _mm_store_ps(max_d2_array,max_d2b);
               
               _mm_store_ps(min_e_array,min_err);
               _mm_store_ps(min_d1_array,min_d1b);
               _mm_store_ps(min_d2_array,min_d2b);
                       
               for (int i = 0; i<4; i++){
                   if (max_e_array[i] > max_e){
                       max_e = max_e_array[i];
                       max_d1 = max_d1_array[i];
                       max_d2 = max_d2_array[i];
                   }                       
                   if (min_e_array[i] < min_e){
                       min_e = min_e_array[i];
                       min_d1 = min_d1_array[i];
                       min_d2 = min_d2_array[i];
                   }                       
               }
               e1 = w01_max + min_e;
               e2 = w00_max - max_e; 
               if (e1 < e2){
                   d1 = min_d1;
                   d2 = min_d2;
                   err_best = e1;
               }
               else{
                   d1 = max_d1;
                   d2 = max_d2;
                   err_best = e2;
               }
               d3 = index(d1,d2);
               d4 = d3;
    
               int i = -1; 
               for (int j=0; j < d2+1; ++j ){
                   i = index(d1,j);
                   if (label(i) == 1){
                       w01_bh = w01_bh + dt(i); 
                   }
                   else{
                       w00_bh = w00_bh + dt(i); 
                   }
               }
               w10_bh = w00_max - w00_bh;
               w11_bh = w01_max - w01_bh;
               
               float eps = 0.001 / N;
               if (err_best < eps){
                   err_best = eps;
               }
               float c0 = 0.0;
               float c1 = 0.0;
               float err_best_n = 1.0 - err_best;
               float alpha = 0.5 * std::log((err_best_n) / err_best);
               if (w00_bh < w01_bh){
                    c0 = alpha;
               }
               else{
                    c0 = -alpha;
               }
                
               if (w10_bh < w11_bh){
                    c1 = alpha;
               }
               else{
                    c1 = -alpha;
               }
               
               py::tuple results(7);
               results[0] = err_best;
               results[1] = d1;
               results[2] = d2;
               results[3] = d3;
               results[4] = d4;
               results[5] = c0;
               results[6] = c1;
    
               return_val = results;
               """
        
        rtrn = weave.inline(code,
                            ['dt','label','index', 'N', 'F'],
                            type_converters = weave.converters.blitz,
                            compiler = 'gcc',
                            extra_compile_args = ['-O3','-msse','-msse2','-ffast-math'],
                            headers = ['<cmath>','<emmintrin.h>'])
        (err_best,d1,d2,d3,d4,c0,c1) = rtrn
        d1 = int(d1)
        d2 = int(d2)
        d3 = int(d3)
        d4 = int(d4)
        self.__bout = np.zeros(N,dtype="bool")
        self.__bout[index[d1,0:d2+1]] = True
        d5 = self.pb.feature_mapping[d1]
        val = np.array([err_best,self.pb.rank, d1, d2, d3, d4, d5, c0, c1])
        return val,self.__bout
