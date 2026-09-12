__all__ = ["LinearExecutor", "AgenticExecutor"]


def __getattr__(name):
	if name == "LinearExecutor":
		from .linear import LinearExecutor
		return LinearExecutor
	if name == "AgenticExecutor":
		from .agentic import AgenticExecutor
		return AgenticExecutor
	raise AttributeError(name)
