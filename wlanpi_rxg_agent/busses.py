from wlanpi_rxg_agent.lib.event_bus import CommandBus, MessageBus

command_bus = CommandBus()
message_bus = MessageBus()
# command_bus.add_handler(CreateCustomerCommand, handle_customer_creation)