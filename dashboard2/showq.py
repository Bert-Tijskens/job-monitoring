"""
Functions and classes for sampling the *showq* output.
"""

import remote
from script     import Data_jobscript
from cfg        import Cfg
from qstatx     import Data_qstat
from sar        import Data_sar
from titleline  import title_line
import          rules
from mycollections import OrderedDict,od_add_list_item,od_last
from cluster    import current_cluster,cluster_properties

import pickle,os,shutil,gzip
from time       import sleep
import datetime

# list of users we want to ignore for the time being...
ignore_users = []

#===============================================================================    
def run_showq():
    """
    1. Run command ``showq -r -p hopper --xml`` on a login node, 
    2. Parse its xml output into an OrderedDict (xmltodict). 
    
    Typical output of ``print(run_showq())`` ::
     
        OrderedDict([('Data', OrderedDict(
            [ ('Object', 'queue')
            , ('cluster', OrderedDict(
                            [ ('@LocalActiveNodes', '167')
                            , ('@LocalAllocProcs', '3305')
                            , ('@LocalConfigNodes', '168')
                            , ('@LocalIdleNodes', '1')
                            , ('@LocalIdleProcs', '54')
                            , ('@LocalUpNodes', '168')
                            , ('@LocalUpProcs', '3360')
                            , ('@RemoteActiveNodes', '0')
                            , ('@RemoteAllocProcs', '0')
                            , ('@RemoteConfigNodes', '0')
                            , ('@RemoteIdleNodes', '0')
                            , ('@RemoteIdleProcs', '0')
                            , ('@RemoteUpNodes', '0')
                            , ('@RemoteUpProcs', '0')
                            , ('@time', '1487065534')
                            ]))
            , ('queue', OrderedDict([ ('@count', '40')
                                    , ('@option', 'active')
                                    , ('job', [ <job entry OrderedDict for each job> ])
                                    ]))
            ]))
        ])
            
    """
    data_showq = remote.run("showq -r -p hopper --xml",post_processor=remote.xml_to_odict)
    return data_showq 

#===============================================================================    
class ShowqJobEntry:
    """
    Class for storing and manipulating a single job entry in the xml output of showq. 
    
    Here is a typical job entry (in xml). It is converted to an :class:`OrderdDict`
    by :func:`xmltodict.parse`:
    
    .. code-block:: html

       <job
       AWDuration="192260"
       Class="q7d"
       DRMJID="393684.hopper"
       EEDuration="106250"
       GJID="393684"
       Group="vsc20213"
       JobID="393684"
       JobName="H2Diss-slabal2o3_MoO3"
       MasterHost="r3c4cn02.hopper.antwerpen.vsc"
       PAL="hopper"
       ReqAWDuration="604800"
       ReqProcs="160"    
       RsvStartTime="1485577392"   
       RunPriority="4970"
       StartPriority="4970" 
       StartTime="1485577392"
       StatPSDed="30761912.000000" 
       StatPSUtl="3691030.208000"
       State="Running"
       SubmissionTime="1485471138" 
       SuspendDuration="0"
       User="vsc20213"
       >
       </job>    
    """
    #---------------------------------------------------------------------------    
    def __init__(self,job_entry):
        self.data = job_entry # OrderedDict
    #---------------------------------------------------------------------------    
    def get_jobid_long(self):
        """ 
        :return: long jobid, includes the cluster on which it was submitted.
        :rtype: str 
        """
        jobid = self.data['@DRMJID']
        return jobid
    #---------------------------------------------------------------------------    
    def get_jobid(self):
        """ 
        :return: short jobid, just the number.
        :rtype: str 
        """
        jobid = self.data['@JobID']
        return jobid
    #---------------------------------------------------------------------------    
    def get_state(self):
        """
        :return: state of the job, 'R', 'C', ...
        :rtype: str, 1 character. 
        """
        state = self.data['@State']
        return state
    #---------------------------------------------------------------------------    
    def get_effic(self,ncores_used_on_mhost=0):
        """
        Return the efficiciency, corrected or uncorrected (*ncores_used_on_mhost*>0).
        
        :param int ncores_used_on_mhost: if larger than zero, represents the number of cores used on mhost and the corrected efficiency is computed (see below), otherwise the uncorrected efficiency is returned.  
         
        According to the Adaptive Computing developers:
        
        "For active jobs Moab reads in the "resources_used.cput" from Torque and 
        divides that by the total processor seconds dedicated to the job. This 
        is the efficiency of the job. Note that this can be a delayed statistic 
        coming from torque so EFFIC is just an estimate until after a job has 
        finished." 
        
        The efficiency is termed uncorrected because in the current setup of hopper
        Torque has no information from the slave nodes, and hence assumes that 
        *resources_used.cput* is 0 for slave nodes. E.g. for a job running on 2 nodes,
        each with 100% efficiency, Moab will report an efficiency of 50% after 100s 
        because it is computed as:
            
        - total processor seconds: 100s * 2 nodes * 20 cores per node = 4000
        - *resources_used.cput* on the master node = 100s * 20 cores per node = 2000
        - *resources_used.cput* on the slave  node = 100s * 20 cores per node = 2000, 
          but Torque sees 0s * 20 cores per node = 0s and thus reports (2000+0)/4000 = 50%
         
        We can scale the efficiency to the master node as
         
        - 50% * number_of_cores_used_by_all_nodes / number_of_cores_used_by_master_node 
          = 50% * 40/20 = 100%
        
        Note that the JobEntry by itself does NOT know the number_of_cores_used_by_master_node
        and thus cannot correct the effic value, unless this value is provided as ncores_used_on_mhost.
         
        The 'corrected' value, obviously provides only information on the master host node
        rather than on the entire job! It is our hope that if the master node is performing 
        well, the slave nodes do so too.        
        """
        remote.err_print('method showq.ShowqJobEntry.get_effic(self, ncores_used_on_mhost) may '
                         'report incorrect values. Use JobSample.get_effic() instead.'
                        , print_time=False
                        ) 
        numerator   = self.data['@StatPSUtl']
        denominator = self.data['@StatPSDed']
        try:
            value = 100*float(numerator)/float(denominator) # [%]
        except ZeroDivisionError:
            value = 100 # seems safe
        if ncores_used_on_mhost>0 and Cfg.correct_effic:
            # scale the effic value to the master host node only, i.e. "correct" it.
            value *= self.get_ncores()/ncores_used_on_mhost 
        return round(value,2)
    #---------------------------------------------------------------------------    
    def get_username(self):
        """
        :return: username of the user that started this job. 
        """
#         :return str: username. 
        value = self.data['@User']
        return value
    #---------------------------------------------------------------------------    
    def get_mhost(self,short=True):
        """ 
        :return: the mhost node (node on wcich the job started.
        """
#         :return str: name of the master compute node. 
        value = self.data['@MasterHost']
        if short:
            value = value.split('.',1)[0]
        return value    
    #---------------------------------------------------------------------------    
    def get_ncores(self):
        """ 
        :return int: total number of cores for this job . 
        """
        value = int( self.data['@ReqProcs'] )
        return value
    #---------------------------------------------------------------------------    

#===============================================================================    
def overview_by_user(arg):
    """
    Sort key for sorting warnings by username
    """
    return arg.split(' ',1)[1]
    #---------------------------------------------------------------------------    

#===============================================================================   
timestamp_format = '%Y.%m.%d.%Hh%M' 
#===============================================================================   
def get_timestamp_now():
    """
    :return: a timestamp based on the current time.
    :rtype: str
    """
    timestamp = datetime.datetime.now().strftime(timestamp_format)
    return timestamp
    #---------------------------------------------------------------------------    

#===============================================================================
class JobSample:
    """
    :param ShowqJobEntry job_entry: the job entry.
    :param Job job: the parent :class: Job object.
    :param str timestamp: the timestamp of the sample.
    """
    #---------------------------------------------------------------------------    
    def __init__(self,job_entry,job,timestamp):
        assert isinstance(job_entry, ShowqJobEntry)
        assert isinstance(job, Job)
        self.showq_job_entry = job_entry
        self.parent_job      = job
        self.timestamp       = timestamp
        self.data_qstat      = Data_qstat( job.jobid )
        self.mhost_job_info  = None# NeighbouringJobInfo(self)
        self.data_sar        = None
        self.details = ''       
    #---------------------------------------------------------------------------
    def check_for_issues(self):
        """
        :return: True (False) if there are (aren't) issues (all rules satisfied) for this JobSample 
        """
        self.mhost_job_info  = NeighbouringJobInfo(self)
        self.warnings = []
        self.overview = ''
        self.details  = ''
        if not self.data_qstat.is_interactive_job(): #interactive jobs are ignored
            for irule,rule in enumerate(rules.the_rules):
                msg = rule.check(self)
                if msg:
                    self.warnings.append(msg)
                    self.parent_job.warning_counts[irule] += 1
        
        if self.warnings:
            self.parent_job.nsamples_with_warnings += 1
            return True
        else:
            return False
    #---------------------------------------------------------------------------
    def compose_overview(self):
        """
        :return: the overview text of the JobSample, composed when asked the first time.
        :rtype: str
        """
        if self.warnings:
            if self.overview:
                return self.overview
            desc = '{} {} {} {}|{}'.format( self.showq_job_entry.get_jobid()
                                          , self.showq_job_entry.get_username()
                                          , self.showq_job_entry.get_mhost()
                                          , self.get_nnodes()
                                          , self.get_ncores()
                                          )
            self.overview = '\n'+( desc.ljust(32)+self.warnings[0] ).ljust(68)+str(self.parent_job.jobscript.loaded_modules(short=True))
            spaces = '\n'+(32*' ')
            for w in self.warnings[1:]:
                w0 = w.split('\n',1)[0]
                self.overview += spaces+w0
        else:
            self.overview = ''
        return self.overview
    #---------------------------------------------------------------------------
    def compose_details(self):
        """
        :return: the details text of the JobSample, composed when asked the first time.
        :rtype: str
        """
        if self.details or not self.warnings:
            return self.details

        self.details = str(self.overview) # make a copy
        self.details += '\n\n#samples with warnings : {} / {} = {}%'.format( self.parent_job.nsamples_with_warnings
                                                                           , self.parent_job.nsamples()
                                                                           , round(100*self.parent_job.nsamples_with_warnings/self.parent_job.nsamples(),2)
                                                                           )
        for irule,count in enumerate(self.parent_job.warning_counts):
            rule = rules.the_rules[irule]
            if count>0:
                self.details +='\n  {:25}: {:5}'.format(rule.warning,count)

        self.details += '\nwalltime used/remaining: {} / {}'.format( self.data_qstat.get_walltime_used()
                                                                   , self.data_qstat.get_walltime_remaining()
                                                                   )
        mem_available = cluster_properties[current_cluster]['mem_avail_gb'](self.get_nodes())
        self.details += '\nmem [GB] used/requested/available: {} / {} / {}'.format( round(self.data_qstat.get_mem_used()     ,3)
                                                                                  , round(self.data_qstat.get_mem_requested(),3) 
                                                                                  , mem_available 
                                                                                  )
        hdr = 'nodes and cores used: '
        nohdr = len(hdr)*' '
        nodes = self.data_qstat.get_exec_host().split('+')
        self.details += '\n'+hdr+nodes[0]
        for node in nodes[1:]:
            self.details += '\n'+nohdr+node
            
        self.details += self.mhost_job_info.to_str() 
            
        if self.data_qstat.node_sar:
            self.details += title_line('sar -P ALL 1 1',width=100,char='-')
            if len(self.data_qstat.node_sar)>1:
                avgs = [self.get_ncores()]
                avgs.extend(6*[0])
                for data_sar in self.data_qstat.node_sar.values():
                    if hasattr(data_sar,'columns'):
                        avgs[1] += data_sar.columns['%user'  ][0]
                        avgs[2] += data_sar.columns['%nice'  ][0]
                        avgs[3] += data_sar.columns['%system'][0]
                        avgs[4] += data_sar.columns['%iowait'][0]
                        avgs[5] += data_sar.columns['%steal' ][0]
                        avgs[6] += data_sar.columns['%idle'  ][0]
                nnodes = self.get_nnodes()
                for i in range(1,7):
                    avgs[i]/=nnodes
                self.details += 'AVERAGE  '+Data_sar.line_fmt.format(*avgs)+'\n'
            for node, data_sar in self.data_qstat.node_sar.items():
                for line in data_sar.data_cores:
                    self.details += node+' '+line +'\n'
        self.details += title_line('Script',width=100,char='-') 
        for line in self.parent_job.jobscript.clean:
            self.details += line+'\n'
        self.details += title_line(width=100,char='-')
            
        return self.details
    #---------------------------------------------------------------------------        
    def walltime(self,hours=False):
        """
        :param bool hours: select the return type and format: *True->int* = #hours, *False->str* = HH:MM:SS.
        :return: the current walltime as reported by qstat, either as the number of hours *(int)*, or as HH:MM:SS *(str)*. 
        :rtype: int or str.
        """
        try:
            wt = self.data_qstat.data['resources_used']['walltime']
            if hours:
                wt = '{:.2f} hrs'.format( hhmmss2s(wt)/3600 )
        except KeyError:
            if hours:
                wt = '? hrs'
            else:
                wt = '??:??:??'
        return wt
    #---------------------------------------------------------------------------        
    def nodedays(self):
        """
        :return: the number of node days comsumed so far, as a formatted str. 
        """
        try:
            wt = self.data_qstat.data['resources_used']['walltime']
            nd = hhmmss2s(wt)*self.get_nnodes()/(3600*24)
            nd = '{:.3f} node days'.format(nd)
        except KeyError:
            nd = '?'
        return nd
    #---------------------------------------------------------------------------        
    def get_effic(self,mhost_only=Cfg.correct_effic):
        """
        Compute the efficiency from the qstat output as:: 
        
            effic = 100 * cputime_used_by_all_cores / (ncores*walltime) # percentage 
        
        This should be close to 100% for well-performing jobs.
        
        :param bool mhost_only: if True, assumes that the reported efficiency is based on information from the mhost node only, an scales the reported value accordingly.
        :return: efficiency as a percentage. 
        
        .. note:: If mhost_only is *True*, and this is a multi-node job, the value reurned 
                  provides **only** information on the mhost node. If it is above the threshold,
                  it is assumed/hoped that the slave nodes are well-performing too, but there is
                  no guarantee. To be certain, the sar output must be inspected (but it is only
                  generated if the mhost is below the threshold). 
                  See allso :func:`ShowqJobEntry.get_effic()`.
        """
        if not hasattr(self,'effic'):
            # we must first compute it.
            try:
                walltime                   = hhmmss2s( self.data_qstat.data['resources_used']['walltime'] )
                cputime_used_by_all_cores  = hhmmss2s( self.data_qstat.data['resources_used']['cput'] )
                ncores   = self.get_ncores()
                self.effic = 100*cputime_used_by_all_cores/(ncores*walltime)
                if mhost_only:
                    ncores_on_mhost = self.get_ncores(cn='mhost')
                    self.effic *= (ncores/ncores_on_mhost) 
            except Exception as e:
                remote.err_print('JobSample.get_effic():',type(e),e)
                self.effic = 0
            
        return self.effic
    #---------------------------------------------------------------------------
    def get_ncores(self,cn='all'):
        """
        :param str cn: compute node name. If equal to 'mhost' the master node is taken.
        :return: number of cores in use on compute node *cn*. If *cn* is *None* the total number of cores in use
        :rtype: int 
        """
        return self.data_qstat.node_cores.ncores(cnode=cn)
    #---------------------------------------------------------------------------        
    def get_nnodes(self):  
        """
        :return: the number of nodes used as reported by qstat.
        """      
        return self.data_qstat.get_nnodes()
    #---------------------------------------------------------------------------        
    def get_nodes(self):
        """
        :return: a list of the (short) node names on which the job is running.
        """        
        return self.data_qstat.node_cores.nodes()
    #---------------------------------------------------------------------------
    def get_jobid(self):
        """
        :return: the jobid
        """
        return self.data_qstat.jobid
    #---------------------------------------------------------------------------
    def get_mhost(self,short=False):
        """
        Return the name of the mhost node, e.g. 'r5c2cn01.hopper.antwerpen.vsc'.
        If *short==True*, it is shortened to the part in front of the first dot: i.e. 
        'r5c2cn01'. 
        """
        if short:
            mhost = self.data_qstat.node_cores.mhost
        else:
            mhost = self.data_qstat.get_master_node()
        return mhost
    #---------------------------------------------------------------------------
    def get_mem(self):
        """
        :return: the maximum of memory used and requested.
        """
        memreqd = self.data_qstat.get_mem_requested()
        memused = self.data_qstat.get_mem_used()
        mem = max(memreqd,memused)
        return mem
    #---------------------------------------------------------------------------
#     def get_effic(self):
#         """
#         from showq or data_qstqt
#         """
#         if 
#         if Cfg.correct_effic:
#             ncores_used_on_mhost = self.get_ncores(cn='mhost')
#         else:
#             ncores_used_on_mhost = 0 
#         value = self.showq_job_entry.get_effic(ncores_used_on_mhost)
#         return value
    #---------------------------------------------------------------------------

#===============================================================================
class NeighbouringJobInfo:
    """
    Info on all jobs running on the master node of a job sample.  
    
    :param JobSample job_sample:
    """
    def __init__(self,job_sample):
        timestamp = job_sample.timestamp
        jobid1 = job_sample.get_jobid()
        self.jobid  = [jobid1]
        self.nnodes = [job_sample.get_nnodes()]
        self.ncores = [job_sample.get_ncores()]
        self.effic  = [job_sample.get_effic ()]
        self.memory = [job_sample.get_mem   ()]
        
        self.mhost = job_sample.get_mhost(short=True)
        neighbouring_jobs = job_sample.parent_job.sampler.mhost_jobs[self.mhost]
        
        for jobid2 in neighbouring_jobs:
            if jobid2 != jobid1:
                job2 = job_sample.parent_job.sampler.jobs[jobid2]
                try:
                    job2sample = job2.get_sample(timestamp)
                except KeyError as e:
                    print(type(e),e,job2)
                    self.nnodes.append(0)
                    self.ncores.append(0)
                    self.effic .append(0)
                    self.memory.append(0)
                else:
                    self.nnodes.append(job2sample.get_nnodes())
                    self.ncores.append(job2sample.get_ncores())
                    self.effic .append(job2sample.get_effic ())
                    self.memory.append(job2sample.get_mem   ())
                self.jobid .append(jobid2)
        self.n = len(neighbouring_jobs)
        if self.n>1:
            self.jobid .append('total:')
            self.nnodes.append(1)
            self.ncores.append(sum(self.ncores))
            effic = 0
            for i in range(self.n):                
                effic += self.effic[i]*self.ncores[i]
            self.effic.append( effic/self.ncores[-1] )
            self.memory.append(sum(self.memory))
    #---------------------------------------------------------------------------        
    def to_str(self):
        """
        Format self as a *str*.
        """
        s = '\nother jobs on {}: '.format(self.mhost)
        if self.n == 1:
            s += 'None.'
        else:
            fmt = '\n  **{}**{:3}|{:2} {:5.1f}% {:7.3f}GB'
            i = 0 
            s+= '{} (total={}).'.format(self.n-1,self.n) 
            s+= fmt.format( self.jobid [i]
                          , self.nnodes[i]
                          , self.ncores[i]
                          , self.effic [i]
                          , self.memory[i]
                          )
            fmt = fmt.replace('*',' ')
            for i in range(1,self.n):
                if self.nnodes[i]!=0:
                    s += fmt.format( self.jobid [i]
                                   , self.nnodes[i]
                                   , self.ncores[i]
                                   , self.effic [i]
                                   , self.memory[i]
                                   )
                else:
                    s+= '\n    {} (no info)'.format(self.jobid[i])
        s+='\n'
        return s
    #---------------------------------------------------------------------------        
        
#===============================================================================
def hhmmss2s(hhmmss):
    """
    Convert time duration in format HH:MM:SS to number of seconds.
    
    :return: duration in seconds
    :rtype: int
    """
    words = hhmmss.split(':')
    assert len(words)==3
    seconds = int(words[2]) + 60*( int(words[1]) + 60*int(words[0]) )
    return seconds 
#-------------------------------------------------------------------------------
        
#===============================================================================
class Job:
    """
    class for storing and manipulating all data (:class:`JobSample` objects)
    related to a job. 
    
    :param str timestamp: the timestamp of the first sample of the job. 
    :param ShowqJobEntry job_entry: a job entry with the showq information of a job from a sample.
    :param Sampler sampler: (a reference to) the :class:`Sampler` object in charge.

    Occasionally, we need to examine other jobs to judge performance of a job, e.g. 
    when a job is not using all resources of the node. For this reason :class:`Job` 
    objects store a reference to the :class:`Sampler` object.  
    """
    #---------------------------------------------------------------------------    
    def __init__(self,timestamp,job_entry,sampler):
        assert isinstance(job_entry,ShowqJobEntry)
        self.jobid    = job_entry.get_jobid()
        self.username = job_entry.get_username()
        self.mhost    = job_entry.get_mhost()
        self.address  = None
    
        self.sampler = sampler         
        
        self.nsamples_with_warnings = 0
        self.warning_counts = len(rules.the_rules)*[0]
            
        self.samples = OrderedDict() #{timestamp:JobSamnple object}
        self.first_timestamp = timestamp
        self.last_timestamp  = None
        self.jobscript       = None
        
        self.add_sample(job_entry,timestamp)
    #---------------------------------------------------------------------------
    def __str__(self):
        s = self.jobid    + '\n'
        s+= self.username + '\n'
        s+= self.mhost    + '\n'
        s+= str(self.samples)
        return s
    #---------------------------------------------------------------------------    
    def add_sample(self,job_entry,timestamp):
        """
        Create a sample with the current *timestamp* from *job_entry*, and add it to the current Job.
        """
        self.last_timestamp = timestamp
        self.samples[timestamp] = JobSample(job_entry,self,timestamp)
    #---------------------------------------------------------------------------
    def timestamps(self):
        """
        :return: an ordered list of timestamps in this Job.
        """
        keys = list(self.samples.keys())
        return keys
    #---------------------------------------------------------------------------
#     def index(self,timestamp):
#         """
#         :return: the index of a timestamp.
#         """
#         index = self.timestamps().index(timestamp)
#         return index
    #---------------------------------------------------------------------------
    def nsamples(self):
        """
        :return: the number of samples in this Job, so far.
        """        
        return len(self.samples)
    #---------------------------------------------------------------------------
    def check_for_issues(self,timestamp):
        """
        Verify wheter this job violates any of the rules for well-performing jobs.
        
        :return: an overview line if not all rules are satisfied, empty *str* otherwise
        """
        sample = self.samples[timestamp] 
        if sample.check_for_issues():
            #there are issues
            if self.jobscript is None:
                self.jobscript = Data_jobscript(self.jobid,self.mhost)
            overview_line = sample.compose_overview()
        else:
            overview_line = ''
        return overview_line
    #---------------------------------------------------------------------------
    def overall_memory_used(self):
        """
        :return: the maximum amount of memory used by this Job, over all its samples.
        """
        mem_used = 0
        for sample in self.samples.values():
            mem_used = max(mem_used,sample.data_qstat.get_mem_used())
        return mem_used
    #---------------------------------------------------------------------------
    def get_details(self,timestamp):
        """
        :return the details text for *timestamp*.
        """
        if not timestamp in self.samples:
            timestamp = self.timestamps()[-1]
        details = self.samples[timestamp].compose_details()
        return details
    #---------------------------------------------------------------------------
    def remove_file(self):
        """
        Remove the *.pickled.gz* file corresponding to this Job.
        """
        fname = 'running/{}_{}.pickled.gz'.format(self.username,self.jobid)
        try:
            os.remove(fname)
        except:
            remote.err_print('failed to remove',fname)
    #---------------------------------------------------------------------------
    def get_sample(self,timestamp='last'):
        """
        Return the sample corresponding to *timestamp*, or, if it is *None*, the last sample.
        """
        if timestamp=='last':
            sample = od_last(self.samples)[1]
        else:
            sample = self.samples[timestamp]
        return sample
    #---------------------------------------------------------------------------
    def get_nnodes(self,timestamp='last'):
        """
        :return: the numer of nodes as reported by the sample at *timestap* 
        """
        sample = self.get_sample(timestamp)
        return sample.get_nnodes()
    #---------------------------------------------------------------------------
    def get_ncores(self,timestamp='last'):
        """
        :return: the numer of nodes as reported by the sample at *timestap* 
        """
        sample = self.get_sample(timestamp)
        return sample.get_ncores()
    #---------------------------------------------------------------------------
    def get_mem(self,timestamp='last'):
        """
        :return: the maximum of memory used and requested for the given timestamp.
        """
        sample = self.get_sample(timestamp)
        return sample.get_mem()
    #---------------------------------------------------------------------------
    def pickle(self,prefix,only_if_warnings=True,verbose=False,compressed=True):
        """
        Pickle this job and compress it using gzip.
        
        :param str prefix: the receiving directory.
        :param bool only_if_warnings: do only pickle if the job has warnings.
        :param bool verbose: if *True*, print the destination file. 
        :param bool compressed: compress after pickling.  
        """
        if (only_if_warnings and self.nsamples_with_warnings) \
        or (not only_if_warnings): 
            #pickle
            if 'running' in prefix:
                fname = '{}_{}.pickled'   .format(self.username,self.jobid)
            else:
                fname = '{}_{}_{}.pickled'.format(self.username,self.jobid,self.timestamps()[-1])
            
            if compressed:
                fpath = os.path.join(prefix,fname+'.gz')
                fo = gzip.open(fpath,'wb') 
            else:
                fo =      open(fpath,'wb')                
            # remove the "upward" object references in the data tree
            # otherwise they waste a lot of disk space
            sampler = self.sampler 
            self.sampler = None
            # job_sample.parent_job
            for job_sample in self.samples.values():
                job_sample.parent_job = None
            # pickle this job                
            pickle.dump(self,fo)
            # finally restore the upward references
            self.sampler = sampler
            # job_sample.parent_job
            for job_sample in self.samples.values():
                job_sample.parent_job = self
            
            if verbose:
                print(' (pickled {})'.format(fpath))
            fo.close()
    #---------------------------------------------------------------------------

#===============================================================================   
def unpickle(fpath,sampler=None,verbose=False):
    """
    Counterpart of Job.pickle()
    
    :param str fpath: path to pickled file. If ending on '.pickled.gz', unzips before unpickling. If ending on '.pickled', unpickle without unzipping. Otherwise try both in that order.   
    :param Sampler sampler: :class:`Sampler` object or :class:`None`.
    :param bool verbose: print the filename of the unpickled file.
    :return: a Job object or :class:`None` if the file does not exist.
    """        
    if fpath.endswith('.pickled.gz'):
        try:
            with gzip.open(fpath,'rb') as fo:
                job = pickle.load(fo)
        except:
            job = None
                    
    elif fpath.endswith('.pickled'):
        try:
            with open(fpath,'rb') as fo:
                job = pickle.load(fo)
        except:
            job = None
    else:
        _fpath = fpath+'.pickled.gz'
        if os.path.exists(_fpath):
            return unpickle(_fpath, sampler=sampler, verbose=verbose)
        else:
            _fpath = fpath+'.pickled'
            if os.path.exists(_fpath):
                return unpickle(_fpath, sampler=sampler, verbose=verbose)
            else:
                job = None
    if job is None:
        if verbose:
            print(' (not found {})\n'.format(fpath))
    else:
        if verbose:
            print(' (unpickled {})\n'.format(fpath))
        # Set the "upward" object references in the data tree
        # otherwise they refer to their version at the moment of pickling
        job.sampler = sampler
        # job_sample.parent_job
        for job_sample in job.samples.values():
            job_sample.parent_job = job                
    return job
#===============================================================================   
class Sampler:
    """
    Class that does the sampling, either through :func:`sample` or :func:`fetch_offline_samples`.
    The frequency of sampling is determined by the caller.
        
    :param int interval: number of seconds between successive samples.
    :param qMainWindow: If *None* prints a progress bar to the terminal during sampling, otherwise uses a Qt4:QProgressDialog.
    """
    #---------------------------------------------------------------------------    
    def __init__(self,interval=None,qMainWindow=None):
        if interval is None:
            self.sampling_interval = Cfg.sampling_interval
        else:
            self.sampling_interval = interval
        self.qMainWindow = qMainWindow
            
        self.overviews = OrderedDict()      # {timestamp:job_overview}
        self.jobs    = {}                   # {jobid    :Job object  }
        self.timestamps = []                # [datetime.strftime(timestamp_format)]
        self.timestamp_jobs = OrderedDict() # {timestamp:[jobids]}
        self.jobids_running_previous = []
    #---------------------------------------------------------------------------    
    def sample(self,verbose=False,show_progress=False):
        """
        Sample the running jobs online (locally). 
        """
        self.data_showq = remote.run("showq -r -p hopper --xml",post_processor=remote.xml_to_odict)
        self.total_nodes_in_use = self.get_total_nodes_in_use()
        # get the job entries
        try:
            job_entries = self.data_showq['Data']['queue']['job']
        except:
            remote.err_print('No jobs running.')
            exit(0)
        # remove jobs
        #  . which have no mhost set
        #  . which have jobid like '390326[1]' (=job array jobs)
        job_entries_filtered = []
        for job_entry in job_entries:
            converted = ShowqJobEntry(job_entry)
            
            # ignore jobs with unknow mhost
            try:
                converted.get_mhost()
            except KeyError:
                print('ignoring',converted.get_jobid_long(), '(mhost unknown)')
                continue
            
            # ignore jobs with jobid containing '[n]'
            jobid = converted.get_jobid()
            if '[' in jobid:
                print('ignoring',job_entry.get_jobid_long(), '(worker job)')
                continue    
            job_entries_filtered.append(converted)
        job_entries = job_entries_filtered
        
        self.n_entries   = len(job_entries)
        
        if self.qMainWindow:
            from PyQt4.QtGui import QProgressDialog,QApplication
            dlg = QProgressDialog('','',0, self.n_entries,self.qMainWindow)
            hdr = 'Sampling #{} : {} {}/{}'
        else:
            if show_progress:
                from progress import printProgress
                hdr = 'sampling showq #{}'.format(len(self.timestamp_jobs)+1)
            
        # create 
        #   . a dict { mhost : [jobid] } with all the jobs running on node mhost 
        #   . a list wit all uncompleted jobids
        # the latter is compared to the jobid list of the previous sample to find
        # out which jobs are finished.
        self.mhost_jobs = OrderedDict()
        self.jobids_running = []
        for job_entry in job_entries:
            mhost = job_entry.get_mhost()
            jobid = job_entry.get_jobid()
            od_add_list_item(self.mhost_jobs,mhost,jobid)
            self.jobids_running.append(jobid)
            try:
                self.jobids_running_previous.remove(jobid)
            except ValueError:
                pass
            #   when this loop has completed, self.jobids_running_previous 
            #   contains only jobides of finished jobs.
        jobids_finished = self.jobids_running_previous
        self.jobids_running_previous = self.jobids_running # prepare for next sample() call
        # pickle finished jobs (if they had issues) and remove them from self.jobs
        os.makedirs('completed', exist_ok=True)
        for jobid in jobids_finished:
            try:
                job = self.jobs.pop(jobid)
            except KeyError:
                continue
            job.pickle('completed/',verbose=True)
            if Cfg.offline:
                job.remove_file()
        timestamp = get_timestamp_now()
        if Cfg.offline:
            os.makedirs ('running',exist_ok=True)
            if os.path.exists('running/timestamp'):
                os.remove('running/timestamp') 
            #   if ths file is absent ojm is sampling. 
            print(title_line(timestamp, char='=', width=100, above=True, below=True),end='')
            
        # loop over the running jobs (job_entries) 
        #pass 1 create jobs and job samples
        for i_entry,job_entry in enumerate(job_entries):
            if job_entry.get_state() != 'Running':
                continue # we only analyze running jobs
            jobid    = job_entry.get_jobid()
            #username = job_entry.get_username()
            od_add_list_item(self.timestamp_jobs,timestamp,jobid)
                        
            if self.qMainWindow:
                progress_message = hdr.format(len(self.timestamp_jobs),jobid,i_entry,self.n_entries)
                dlg.setLabelText(progress_message)
                dlg.setValue(i_entry)
                QApplication.processEvents()
            else:
                if show_progress:                
                    printProgress(i_entry, self.n_entries, prefix=hdr, suffix='jobid='+jobid, decimals=-1)
                
            job = self.jobs.get(jobid,None)
            if job is None:
                # this job is encountered for the first time
                job = Job(timestamp,job_entry,self)
                self.jobs[jobid] = job 
            else:
                job.add_sample(job_entry,timestamp)
                if job.sampler is None:
                    remote.err_print('### strange')
                    job.sampler = self
        
        if self.qMainWindow:
            # terminate QProgressDialog
            dlg.setValue(self.n_entries)
            QApplication.processEvents()
            # start new QProgressDialog
            dlg = QProgressDialog('','',0, self.n_entries,self.qMainWindow)
            hdr = 'Checking rules #{} : {} {}/{}'
        else:
            if show_progress:                
                # terminate printProgress            
                printProgress(self.n_entries, self.n_entries, prefix=hdr, suffix='', decimals=-1)
                # start new printProgress            
                hdr = 'Checking rules #{}'.format(len(self.timestamp_jobs)+1)
                
        #pass 2 add NeighbouringJobInfo and check the rules
        overview = [] # one warning per job with issues, jobs without issues are skipped
        i_entry = 0
        for jobid,job in self.jobs.items():
            #progress
            if self.qMainWindow:
                progress_message = hdr.format(len(self.timestamp_jobs),jobid,i_entry,self.n_entries)
                dlg.setLabelText(progress_message)
                dlg.setValue(i_entry)
                QApplication.processEvents()
            else:
                if show_progress:                
                    printProgress(i_entry, self.n_entries, prefix=hdr, suffix='jobid='+jobid, decimals=-1)
            i_entry += 1
            #the real work
            overview_line = job.check_for_issues(timestamp)
            if overview_line:
                overview.append(overview_line)
                if verbose:
                    print('\n'+timestamp+'\n')
                    print(job.get_details(timestamp))
                if Cfg.offline:
                    job.pickle('running', verbose=verbose)
                    
        if self.qMainWindow:
            # terminate QProgressDialog
            dlg.setValue(self.n_entries)
            QApplication.processEvents()
        else:
            if show_progress:                
                # terminate printProgress
                printProgress(self.n_entries, self.n_entries, prefix=hdr, suffix='', decimals=-1)
            for line in overview:
                print(line,end='')
            print('\nWell performing jobs: {}/{}'.format(self.n_entries-len(overview),self.n_entries))
        print(self.total_nodes_in_use)

        if Cfg.offline:
            # notify that sampling has finished.. 
            with open('running/timestamp','w') as f:
                f.write(timestamp)

        self.overviews[timestamp] = self.overview_list2str(overview)
        
        self.timestamps.append(timestamp)
        #    this must be the last statement because the gui otherwise sees a timestamp which is not ready.
        return timestamp
    #---------------------------------------------------------------------------
    def get_total_nodes_in_use(self):
        """
        :return: a str describing the fraction of nodes in use. 
        """
        if hasattr(self,'data_showq'):
            s = 'nodes in use: {}/{}'.format( self.data_showq['Data']['cluster']['@LocalActiveNodes']
                                            , self.data_showq['Data']['cluster']['@LocalConfigNodes'] )
            self.total_nodes_in_use = s
            return s
        else:
            if hasattr(self,'total_nodes_in_use'):
                return self.total_nodes_in_use
            else:
                return ''
    #---------------------------------------------------------------------------
    def get_remote_timestamp(self):
        """
        :return: the last sample's timestamp from the offline job monitor. If ojm.py is in the process of sampling an empty string is returned. 
        """
        try:
            lines = remote.run('cd data/jobmonitor/running/; cat timestamp',post_processor=remote.list_of_lines)
            return lines[0]
        except:
            return ''
    #---------------------------------------------------------------------------
    def fetch_offline_samples(self):
        """
        Sample the running jobs from the offline job monitor. The remote directory '~/data/jobmonitor/running'
        examined to see if there are new samples available. These are copied to the local directory ./offline/running
        """
        shutil.rmtree('offline/running')
        os.makedirs('offline/running'  ,exist_ok=True)
        #os.makedirs('offline/completed',exist_ok=True)
        timestamp = self.get_remote_timestamp()
        while not timestamp:
            sleep(60)
            timestamp = self.get_remote_timestamp()
        if self.timestamps:
            if timestamp==self.timestamps[-1]:
                return # this timestamp is already in the samples
        self.timestamps.append(timestamp)
        filenames = remote.glob('*.pickled.gz','data/jobmonitor/running/')
        self.n_entries = 0
        for filename in filenames:
            if not filename: # empty line
                continue
            lfname =         'offline/running/'+filename
            rfname = 'data/jobmonitor/running/'+filename
            print('copying '+rfname,'to',lfname,end='')
            try:
                remote.copy_remote_to_local(lfname,rfname)
                print(' - copied')
            except:
                print(' - failed')
                continue
            job = unpickle('offline/running/'+filename,sampler=self)
            self.add_offline_job(job)
            self.n_entries += 1
        self.overviews[timestamp] = self.overview_list2str(self.overviews[timestamp])
    #---------------------------------------------------------------------------
#     def timestamp(self,i=-1):
#         return self.timestamps[i]
    #---------------------------------------------------------------------------    
    def overview_list2str(self,overview_list,key=overview_by_user,reverse=True):
        """
        Sort the *overview_list* according to *key* and *reverse* and convert to plain text. 
        """
        overview_list.sort(key=key,reverse=reverse)
        n_jobs = self.n_entries
        n_warn = len(overview_list)
        text = 'Jobs running well: {}/{}, efficiency threshold = {}%'.format(n_jobs-n_warn,n_jobs,Cfg.effic_threshold)
        s = self.get_total_nodes_in_use()
        if s:
            text+= ', '+s
        text+= ''.join(overview_list) 
        return text
    #---------------------------------------------------------------------------
    def nsamples(self):
        """
        :return: the number of samples.
        """
        return len(self.timestamps)
    #---------------------------------------------------------------------------
    def add_offline_job(self,job):
        """
        Add an offline monitored *job* to the sampler.        
        """
        self.jobs[job.jobid] = job
        for timestamp,job_sample in job.samples.items():
            od_add_list_item(self.timestamp_jobs,timestamp,job.jobid)
            overview_line = job_sample.compose_overview()
            if not timestamp in self.overviews:
                self.overviews[timestamp] = [overview_line]
            else:
                overview = self.overviews[timestamp] 
                if isinstance(overview,str):
                    lines = overview.split('\n')
                    self.overviews[timestamp] = []
                    overview = self.overviews[timestamp]
                    for line in lines:
                        if not line.endswith('\n'):
                            line += '\n'
                        overview.append(line)
                overview.append(overview_line)   
        self.total_nodes_in_use = job.sampler.get_total_nodes_in_use()
    #---------------------------------------------------------------------------
    def when_done_adding_offline_jobs(self):
        """
        Sort offline monitored jobs.
        """
        self.timestamps.sort()
        for jobid_list in self.timestamp_jobs.values():
            jobid_list.sort()
    #---------------------------------------------------------------------------    
    
################################################################################
# test code below
################################################################################
if __name__=="__main__":
    remote.connect_to_login_node()

    sampler = Sampler()
    timestamp = sampler.sample()
    
    current_jobids = sampler.timestamp_jobs[timestamp]
    for jobid in current_jobids:
        job_sample = sampler.jobs[jobid].samples[timestamp]
        print( job_sample.compose_details(),end='')
        
    print('\n--finished--')
