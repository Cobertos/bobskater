from setuptools import setup

setup(
    name='bobskater',
    version='0.2.0',
    description='AST based Obfuscator for Python',
    long_description=open('README.md', 'r').read(),
    long_description_content_type="text/markdown",
    url='https://github.com/Cobertos/bobskater/',
    author='Peter "Cobertos" Fornari',
    author_email='cobertosrobertos@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.4',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Software Development :: Code Generators'
    ],
    keywords='bobskater obfuscator obfuscation minifier mangler python',
    packages=['bobskater'],
    install_requires=['astunparse']
)
