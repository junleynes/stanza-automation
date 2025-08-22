import os
import sys
import time
import subprocess
import logging
import win32serviceutil
import win32service
import win32event
import servicemanager
from threading import Thread, Lock, Semaphore
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configuration
STABILITY_THRESHOLD = 10
MAX_WAIT_TIME = 600
INITIAL_CHECK_INTERVAL = 1
MAX_CONCURRENT_PROCESSES = 5
MIN_FILE_AGE = 5

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("file_watcher.log"),
        logging.StreamHandler()
    ]
)

class RobustFolderWatchHandler(FileSystemEventHandler):
    def __init__(self, script_path, is_python):
        self.script_path = script_path
        self.is_python = is_python
        self.processing_files = set()
        self.lock = Lock()
        self.semaphore = Semaphore(MAX_CONCURRENT_PROCESSES)

    def wait_for_stable_file(self, file_path):
        """Enhanced stability check with file age verification."""
        last_size = -1
        unchanged_count = 0
        wait_interval = INITIAL_CHECK_INTERVAL
        start_time = time.time()
        file_creation_time = os.path.getctime(file_path)

        while unchanged_count < STABILITY_THRESHOLD:
            try:
                if time.time() - file_creation_time < MIN_FILE_AGE:
                    logging.debug(f"File too new, waiting: {file_path}")
                    unchanged_count = 0
                    time.sleep(wait_interval)
                    continue

                current_size = os.path.getsize(file_path)
                if current_size == last_size:
                    unchanged_count += 1
                    wait_interval = min(wait_interval * 1.5, STABILITY_THRESHOLD)
                else:
                    unchanged_count = 0
                    wait_interval = INITIAL_CHECK_INTERVAL
                last_size = current_size
            except OSError as e:
                logging.warning(f"Error accessing {file_path}: {e}")
                unchanged_count = 0
            
            if time.time() - start_time > MAX_WAIT_TIME:
                logging.error(f"Timeout waiting for {file_path} to stabilize")
                return False
            
            time.sleep(wait_interval)
        
        return True

    def run_script(self, file_path):
        """Execute the script with enhanced error handling."""
        try:
            with self.semaphore:
                logging.info(f"Starting processing: {file_path}")
                
                cmd = ["python", self.script_path, file_path] if self.is_python else [
                    "powershell", "-File", self.script_path, file_path]
                
                result = subprocess.run(
                    cmd,
                    check=True,
                    timeout=3600,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                logging.info(f"Completed processing: {file_path}")
                if result.stdout:
                    logging.debug(f"Script output: {result.stdout}")
        
        except subprocess.CalledProcessError as e:
            logging.error(f"Script failed for {file_path}. Error: {e.stderr}")
        except subprocess.TimeoutExpired:
            logging.error(f"Script timeout for {file_path}")
        except Exception as e:
            logging.error(f"Unexpected error processing {file_path}: {str(e)}")
        finally:
            with self.lock:
                self.processing_files.discard(file_path)

    def on_created(self, event):
        if event.is_directory:
            return

        file_path = event.src_path
        logging.info(f"Detected new file: {file_path}")

        with self.lock:
            if file_path in self.processing_files:
                logging.info(f"Already processing {file_path}, skipping")
                return
            self.processing_files.add(file_path)

        def process():
            if self.wait_for_stable_file(file_path):
                self.run_script(file_path)
            else:
                logging.warning(f"Failed to stabilize: {file_path}")
                with self.lock:
                    self.processing_files.discard(file_path)

        Thread(target=process, daemon=True).start()

class FileWatcherService(win32serviceutil.ServiceFramework):
    _svc_name_ = "StanzaAutomationWatchdog"
    _svc_display_name_ = "Stanza Automation Watchdog Service"
    _svc_description_ = "Monitors folders and processes new files"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.observer = None
        self.is_running = False

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.observer:
            self.observer.stop()
        self.is_running = False
        win32event.SetEvent(self.hWaitStop)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):  # Corrected method name (was SvcDoCommand)
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self.start_watching()

    def start_watching(self):
        folder_mapping = {
            r"D:\STANZA_SHARE\STANZA_TRANSIT\AUTOMATION\SOURCE": (
                r"D:\STANZA_SHARE\POSTMAMS\scripts\STANZA-AUTOMATION\stanza-automation.py", 
                True
            ),
        }

        self.observer = Observer()
        for folder, (script_path, is_python) in folder_mapping.items():
            if not os.path.exists(script_path):
                logging.error(f"Script not found: {script_path}")
                continue
            handler = RobustFolderWatchHandler(script_path, is_python)
            self.observer.schedule(handler, folder, recursive=True)
            logging.info(f"Watching folder: {folder} (recursive)")
        
        self.observer.start()
        logging.info("Folder watch service started")
        self.is_running = True

        while self.is_running:
            time.sleep(1)

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(FileWatcherService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(FileWatcherService)