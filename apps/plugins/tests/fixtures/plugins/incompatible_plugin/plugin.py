class Plugin:
    name = "Future Plugin"
    version = "1.0.0"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok"}
