# from wlanpi_rxg_agent.rxg_agent import startup
import uvicorn

import wlanpi_rxg_agent.rxg_agent as rxg_agent

# startup()

uvicorn.run(rxg_agent.app, host="0.0.0.0", port=8200)