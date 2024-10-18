import daemon

import rxg_agent

with daemon.DaemonContext():
    rxg_agent.main()