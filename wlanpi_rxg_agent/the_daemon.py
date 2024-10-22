import daemon
from wlanpi_rxg_agent import rxg_agent

with daemon.DaemonContext():
    rxg_agent.main()
