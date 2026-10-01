class NginxConfigError(Exception):
    def __init__(self, message: str, verbose_output: str = ""):
        super().__init__(message)
        # nginx's debug-level output for the failed test, kept apart from the
        # message: it can echo parts of the config (DB passwords), so it must
        # never end up in the logs - see WordPressNginxController._keep_rejected_config.
        self.verbose_output = verbose_output


class NginxReloadError(Exception):
    pass


class WordpressSiteLookupError(Exception):
    pass
