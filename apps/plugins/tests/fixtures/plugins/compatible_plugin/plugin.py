class Plugin:
    name = "Test Plugin"
    version = "1.0.0"
    fields = []
    actions = [{"id": "test", "label": "Test"}]

    def run(self, action_id, params, context):
        return {"status": "ok"}
