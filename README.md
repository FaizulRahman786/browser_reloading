# Browser Recovery Research — Starter Experiment

This is a local-only research prototype for studying ambiguous outcomes in browser automation. It is not a patentability conclusion and it does not interact with external websites.

## 1. Requirements
- Windows 10/11
- Python 3.10 or newer
- Internet access for installing packages and Chromium

## 2. Create a virtual environment (PowerShell)
```powershell
py --version
mkdir browser-recovery-research
cd browser-recovery-research
```
Extract the ZIP contents into this folder, then run:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

If PowerShell blocks activation, use:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
and run the scripts with `.\.venv\Scripts\python.exe`.

## 3. Terminal 1: start the local mock server
```powershell
python app.py
```
Leave this terminal open. The app listens only on `127.0.0.1:5055`.

## 4. Terminal 2: run the naive baseline
Open a second PowerShell window, go to this folder, activate the environment, and run:
```powershell
python baseline.py
```

The script deliberately uses a 500 ms confirmation timeout while the server waits 2 seconds before replying. The server records each operation before sending confirmation. The baseline retries after timeout without checking the actual server-side result.

## 5. What to record
- Did the first attempt time out?
- Did the second attempt time out?
- How many submissions did `/status` report?
- Did the result match the hypothesis?

Expected for this deliberately constructed demonstration: the baseline can record two submissions because it retries without reconciling the first result. This only demonstrates a known failure mode; it does NOT establish that a new solution is novel or patentable.

## 6. Safety and research notes
- Use only this local mock app for the experiment.
- Do not point the prototype at real booking, payment, school, or account systems.
- Keep your research notes private while patent options are being assessed.
- Before filing, perform a broader patent and non-patent literature search and consult a registered patent agent.
