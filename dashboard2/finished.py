"""
Main program for job monitoring of finished jobss
"""
from PyQt4 import QtGui,uic
import sys
import argparse
from _collections import OrderedDict
import glob
from _pickle import load

from mail import address_of
from ignoresignals import IgnoreSignals
# from showq import Job
#===================================================================================================
def completed_jobs_by_user(arg):
    """
    sort key for sorting finished jobs by username
    """
    return arg.split('_',1)[0]
#===================================================================================================
def completed_jobs_by_jobid(arg):
    """
    sort key for sorting finished jobs by jobid
    """
    return arg.split('_',2)[1]
#===================================================================================================
def completed_jobs_by_time(arg):
    """
    sort key for sorting finished jobs by username
    """
    return arg.split('_',3)[2]#.split('.',1)[0]
#===================================================================================================
class JobHistory:
    """"""
    #---------------------------------------------------------------------------------------------------------         
    def __init__(self,job):
        self.job = job
        self.timestamp_begin = []
        line = 1
        try:
            self.address = self.job.address
        except:
            self.address = address_of(self.job.username)
        text = self.address
        for i,timestamp in enumerate(self.job.timestamps()):
            text += '\n### '+timestamp+' '+(59*'#')
            self.timestamp_begin.append(line)
            timestamp_details = job.get_details(timestamp)+'\n'
            if i>0: # remove the script, it already appears in the first sample.
                pos = timestamp_details.find('*** Script')
                if pos > -1:
                    timestamp_details = timestamp_details[:pos]
            line += timestamp_details.count('\n') + 1
            text += timestamp_details
        text += '\n'+80*'#'
        self.details = text
        self.current_timestamp = 0
    #---------------------------------------------------------------------------------------------------------         

#===================================================================================================
class Finished(QtGui.QMainWindow):
    """
    """
    #---------------------------------------------------------------------------------------------------------         
    def __init__(self,verbose=False
                     ,test__ =False
                     ):
        """"""
        super(Finished, self).__init__()
        self.ui = uic.loadUi('finished.ui',self)
        self.setWindowTitle('Job monitor - FINISHED jobs')
        self.verbose = verbose
        self.test__  = test__
        self.ignore_signals = False
        self.current_job = None
        
        font = QtGui.QFont()
        font.setFamily('Monaco')
        font.setPointSize(11)
        self.ui.qwOverview.setFont(font)
        self.ui.qwDetails .setFont(font)
        
        self.get_file_list()
        
        self.show()
        
    #---------------------------------------------------------------------------------------------------------
    # qwOverview handling
    #---------------------------------------------------------------------------------------------------------
    def get_file_list(self):
        self.map_fname_job  = OrderedDict()
        self.fnames = glob.glob('completed/*.pickled')
        for fname in self.fnames:
            self.map_fname_job[fname] = None
        self.sort_overview()
    #---------------------------------------------------------------------------------------------------------         
    def on_qwOverviewRefresh_pressed(self):
        self.get_file_list()
    #---------------------------------------------------------------------------------------------------------
    def on_qwOverviewReverse_stateChanged(self):
        print('on_qwOverviewReverse_stateChanged')
        self.sort_overview()
    #---------------------------------------------------------------------------------------------------------         
    def on_qwOverviewUser_toggled(self):
        print('on_qwOverviewUser_toggled')
        if self.ui.qwOverviewUser.isChecked():
            self.sort_overview()
    #---------------------------------------------------------------------------------------------------------         
    def on_qwOverviewJobid_toggled(self):
        print('on_qwOverviewJobid_toggled')
        if self.ui.qwOverviewJobid.isChecked():
            self.sort_overview()
    #---------------------------------------------------------------------------------------------------------         
    def on_qwOverviewTime_toggled(self):
        print('on_qwOverviewTime_toggled')
        if self.ui.qwOverviewTime.isChecked():
            self.sort_overview()
    #---------------------------------------------------------------------------------------------------------         
    def sort_overview(self):
        print('sort_overview')
        if self.ui.qwOverviewUser.isChecked():
            sort_key = completed_jobs_by_user
        elif self.ui.qwOverviewJobid.isChecked():
            sort_key = completed_jobs_by_jobid
        elif self.ui.qwOverviewTime.isChecked():
            sort_key = completed_jobs_by_time
        else:
            return
        self.fnames.sort(key=sort_key,reverse=self.ui.qwOverviewReverse.isChecked())
        self.show_overview()
    #---------------------------------------------------------------------------------------------------------         
    def show_overview(self):
        """"""
        text = '\n'
        text+= '\n'.join(self.fnames)
        self.ui.qwOverview.setPlainText(text)
    #---------------------------------------------------------------------------------------------------------         
    def on_qwOverview_cursorPositionChanged(self):
        """"""
        if self.ignore_signals:
#             print('ignored')
            return
#         print('on_qwOverview_cursorPositionChanged')
        cursor = self.ui.qwOverview.textCursor()
        cursor.select(QtGui.QTextCursor.LineUnderCursor)
        pickled = cursor.selectedText()
        with IgnoreSignals(self):
            self.ui.qwOverview.setTextCursor(cursor)
        print('selected:',pickled)
        self.show_details(pickled)
    #---------------------------------------------------------------------------------------------------------         
    # qwDetails handling
    #---------------------------------------------------------------------------------------------------------             
    def show_details(self,fname):
        """"""
        if fname:
            jobh = self.map_fname_job[fname]
            if jobh is None:
                file = open(fname,'rb')
                jobh = JobHistory(load(file))    
                self.map_fname_job[fname] = jobh
            else:
                jobh.current_timestamp = 0
            self.ui.qwDetailsJobid.setText(jobh.job.username+' '+jobh.job.jobid)
            self.ui.qwDetails.setPlainText(jobh.details)
            self.current_job = jobh # used by move_details
            self.ui.qwDetailsNSamples.setText('{} / {}'.format(1,jobh.job.nsamples()))
            self.ui.qwDetailsTimestamp.setText(jobh.job.timestamps()[0])
    #---------------------------------------------------------------------------------------------------------
    def on_qwDetailsFirst_pressed(self):
        print('on_qwDetailsFirst_pressed')
        self.move_details(index=0)
    #---------------------------------------------------------------------------------------------------------
    def on_qwDetailsFBwd_pressed(self):
        print('on_qwDetailsFBwd_pressed')
        self.move_details(delta=-5)
    #---------------------------------------------------------------------------------------------------------         
    def on_qwDetailsBwd_pressed(self):
        print('on_qwDetailsBwd_pressed')
        self.move_details(delta=-1)
    #---------------------------------------------------------------------------------------------------------         
    def on_qwDetailsFwd_pressed(self):
        print('on_qwDetailsFwd_pressed')
        self.move_details(delta=1)
    #---------------------------------------------------------------------------------------------------------         
    def on_qwDetailsFFwd_pressed(self):
        print('on_qwDetailsFFwd_pressed')
        self.move_details(delta=5)
    #---------------------------------------------------------------------------------------------------------         
    def on_qwDetailsLast_pressed(self):
        print('on_qwDetailsLast_pressed')
        self.move_details(index=-1)
    #---------------------------------------------------------------------------------------------------------         
    def move_details(self,index=None,delta=None):
        i = index
        if delta:
            i = self.current_job.current_timestamp + delta
            # make sure index i is in the valid range.
            i = max(0,i)
            i = min(i,self.current_job.job.nsamples()-1)
        self.current_job.current_timestamp = i
        self.ui.qwDetailsNSamples.setText('{} / {}'.format(i,self.current_job.job.nsamples()))
        self.ui.qwDetailsTimestamp.setText(self.current_job.job.timestamps()[i])
        line = self.current_job.timestamp_begin[i]
        cursor = self.ui.qwDetails.textCursor()
        current_block = cursor.blockNumber()
        nlines_to_move = line - current_block
        if nlines_to_move > 0:
            moveop = QtGui.QTextCursor.Down
        elif nlines_to_move < 0:
            nlines_to_move = -nlines_to_move
            moveop = QtGui.QTextCursor.Up
        else:
            moveop = QtGui.QTextCursor.NoMove
        cursor.movePosition(moveop,n=nlines_to_move)
        cursor.select(QtGui.QTextCursor.LineUnderCursor)
        self.ui.qwDetails.setTextCursor(cursor)

    #---------------------------------------------------------------------------------------------------------
    def on_qwMail_pressed(self):
        """
        copy the email address of the user of the current job to the clipboard
        """
        if self.current_job is None:
            return
        print(address)
        clipboard = QtGui.qApp.clipboard()
        clipboard.setText(address)
    #---------------------------------------------------------------------------------------------------------

if __name__=='__main__':

    app = QtGui.QApplication(sys.argv)
    
    parser = argparse.ArgumentParser('finished')
    parser.add_argument('--verbose',action='store_true')
    parser.add_argument('--test__' ,action='store_true')
    args = parser.parse_args()
    print(args)
    finished = Finished(verbose = args.verbose
                       ,test__  = args.test__
                       )
    finished.show()
    
    sys.exit(app.exec_())

    print('\n-- finished --')