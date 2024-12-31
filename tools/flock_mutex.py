import fcntl
from os import getpid


class Flock_mutex(object):
	"""
	An object that acts as a context manager for acquiring a
	mutex lock on file with a given name.

	To lock a critical section of code:

	with Flock_mutex(FILE_NAME):
		Run critical code here

	Note: the file must be writeable and it will be
	overwritten with process id of the locking process.
	"""

	def __init__(self, file_name):
		self.file_name = file_name

	def __enter__(self):
		"""
		Acquires the lock.
		"""
		self.file_object = open(self.file_name, 'wt')
		fcntl.flock(self.file_object, fcntl.LOCK_EX)
		self.file_object.write(str(getpid()) + '\n')

	def __exit__(self, *args):
		"""
		Releases the lock.
		"""
		try:
			fcntl.flock(self.file_object, fcntl.LOCK_UN)
		finally:
			self.file_object.close()
