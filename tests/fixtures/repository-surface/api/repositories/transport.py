def _helper(client):
    return client.rpc("claim_message")


def get_message(client):
    _helper(client)
    return client.table("messages")


def dead(client):
    return client.table("secrets")
