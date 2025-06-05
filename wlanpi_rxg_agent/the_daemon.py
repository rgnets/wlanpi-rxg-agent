import daemon
import uvicorn

from wlanpi_rxg_agent import rxg_agent

with daemon.DaemonContext():
    uvicorn.run(rxg_agent.app, host="0.0.0.0", port=8200)
