from utils import format_data, validate_token

class PipelineService:
    def process(self, raw_input):
        clean = format_data(raw_input)
        return clean

    def verify(self, auth_header):
        return validate_token(auth_header)
