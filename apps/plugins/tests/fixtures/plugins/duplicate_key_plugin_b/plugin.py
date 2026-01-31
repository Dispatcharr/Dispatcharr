class Plugin:
    name = "Duplicate Key Plugin B"
    version = "2.0.0"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok", "plugin": "b"}
