"""one - the program from step 07 of task 30.

One program that runs all the time, holds every run, writes everything that
happens into one list, decides what a run may do, and answers a terminal, a
browser, Rouh's voice and the phone over one set of messages.

The name is a label: it is the one program and it keeps one list.
"""

#: The version a person says out loud: MAJOR.MINOR.PATCH, and the one place it
#: is written down. Patch for a fix, minor for a new feature, major for a break;
#: the rule is in one/README.md, under "Its version". Move it in the same commit
#: as the change it describes, so the number and the code can never disagree.
#:
#: 1.0.0 is where the numbering starts rather than where the program did. It had
#: been serving runs, terminals, the phone, a paired browser and Rouh's voice
#: for a while under "0.1.0", a number nobody had moved since the first day and
#: which therefore told nobody anything. 1.0.0 is the first version whose shape
#: is written down and whose number is promised to move.
__version__ = "1.4.0"
