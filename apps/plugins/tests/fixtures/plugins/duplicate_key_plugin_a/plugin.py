class Plugin:
    name = "Duplicate Key Plugin A"
    version = "1.0.0"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok", "plugin": "a"}
