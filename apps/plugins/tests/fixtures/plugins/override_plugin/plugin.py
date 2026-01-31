class Plugin:
    name = "Class Name"
    version = "1.0.0"
    description = "From class"
    fields = []
    actions = []

    def run(self, action_id, params, context):
        return {"status": "ok"}
