from lib.event_bus import CommandBus, MessageBus

command_bus = CommandBus(locking=False)
message_bus = MessageBus()
# command_bus.add_handler(CreateCustomerCommand, handle_customer_creation)