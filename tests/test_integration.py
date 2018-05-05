'''
Integration tests for bobskater obfuscation
'''
import unittest

from bobskater.obfuscate import obfuscateString

class TestBobskater(unittest.TestCase):
    '''
    Tests integration of multiple components (high level functions)
    '''
    def test_basic_locals_arguments_no(self):
        '''will obfuscate locals, functions, arguments, but not module level identifiers and functions same'''
        #arrange
        code = """
def testOuter(*args, **kwargs):
    eval("1+1")
    arp=2
    def test(who,dat,man):
        arp2=3
        eval("2+2")
        return who+dat+man
    return test(*args, **kwargs)
        """

        #act
        print(obfuscateString(code))
        exec(obfuscateString(code), globals())

        #assert
        self.assertEqual(testOuter(2,3,4),9)

    def test_basic_locals_arguments_no(self):
        '''will not obfuscate kwargs'''
        #arrange
        code = """
def testOuter(babl=1, mopl=2, roopl=3):
    def test(map,cap,rap):
        return map*cap-rap
    return test(babl, mopl, roopl)
        """

        #act
        print(obfuscateString(code))
        exec(obfuscateString(code), globals())

        #assert
        self.assertEqual(testOuter(mopl=4, roopl=10),-6)