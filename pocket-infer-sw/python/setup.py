from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='pocketinfer',
    version='0.1.0',
    packages=find_packages(),
    # Additional metadata
    author='Andrew Tergis',
    author_email='theterg@gmail.com',
    description='Python code supporting the pocket-infer device',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    license='MIT',
    install_requires=requirements,
    include_package_data=True,
    entry_points={
        'console_scripts': ['pocketinfer-service=pocketinfer.service:main'],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
)
