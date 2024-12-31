def log_if_logger(logger, level, message):
	if logger is not None:
		logger.log(level, message)

