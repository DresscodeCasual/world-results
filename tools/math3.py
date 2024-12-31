def isclose(a, b, rel_tol=1e-9, abs_tol=0.0):
	"As propsed by PEP 485 (method strong) and implemented in math.isclose in ver > 3.5"

	if a == b:
		return True
	return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)
