from pymessagebus import CommandBus, MessageBus

command_bus = CommandBus()
message_bus = MessageBus()
# command_bus.add_handler(CreateCustomerCommand, handle_customer_creation)