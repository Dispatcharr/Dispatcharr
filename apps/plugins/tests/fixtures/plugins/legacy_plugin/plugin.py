class Plugin:
    name = "Legacy Plugin"
    version = "2.0.0"
    description = "A legacy plugin without manifest"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok"}
