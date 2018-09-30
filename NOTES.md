// warning when overwriting data
  //not a problem since we filter out sentences that are not data=null
//focus search bar after open
//create mock cards when only sentence examples
  //shouldn't happen often now with cedict
//add cedict
//when filterering, disregard difficulty
add decks link
  show how many sentences there are for current card shown in study
ask if user wants to add words after adding cards/cloze
  which template?


Since we include cedict from the start, let's ignore other vocab the user has
Focus on creating a connection between user notes and cedict entries
Get rid of jieba, dont think it adds anything

1. Index sentences once, using cedict entries
2. Tie user notes to cedict entries

----------
2018-07-10
----------

Keep rememberberry database as a number of flat files, on a specified format
each row in the format
hash/simpl/trad/1-2:hash2/2-3,3-4:hash3/ 

Everything has hash links like IPFS, which is good becuase:
1. No need for a central authority on unique identifiers
2. No difficulty collaborating, and using said identifiers
3. Easy for third parties to integrate with the same data format for
   copyrighted content, no need to "reserve" identifiers

However:
1. Need an update list, with hash to hash mappings when hashes changed 
   Can have "hash1 hash2 datetime" in a separate file, and then purge older ones

Use as short hashes as we can to reduce size? Or allow to append data in case of collision
sha-64 hash = aBEvTGsbWyx
              43c7nRejfxy
              AXJU9Xp4Ltz
              bmD2ApdnBBd

Chance for collision:
k = 10e6
N = pow(2, 64)
prob_collision = 1 - math.exp(-k*(k-1)/(2*N))
> 2.710501486702377e-06

Refer to media files with ipfs hashes
Rather than having licence for each entry, keep all from a certain source in the same file
and keep the license up top

How to make a fast index for sentences?
With 5 million sentences and >1 GB of data, probably best to to keep it on file and
not in memory
We have these files:
  a. The files containing the data
  b. A file with a sorted list of all the sentences, their current score, and where
     to find it in the data file
  c. a reverse map of 2.
  d. a word to sentence index
Do a full pass the first time, then when an anki card is updated we update the indices
by doing a word to sentence lookup, then recalculating the score and reordering
by
 1. looking up sentence indices in d. 
 2. for each sentence, 

Or just use sqlite:
  No need to build ad-hoc indexes
  Lots of tools available, probably some way to version and merge


Rememberberry tables:
  one table with sentences/items with columns:
    rememberberry_hash prev_version content(json) content_type(points to schema and license)
  one table with links beteen hashes:
    id to_hash from_hash position(json, start/end, crop etc)
  one table with updates:
    id from_hash to_hash
User tables:
  one table with connection between notes and rememberberry
    note_id rememberberry_hash
  one table with scores:
    rememberberry_hash sum_score max_score

Initially, run an initial pass and set the sum_score by going through each user word,
go through all the links to that word and increment the user score of the corresponding sentence

After that, whenever anki updates a card, go through links and apply the difference in strength


----------
2018-07-14
----------

import importlib
from rememberberry import indexing
importlib.reload(indexing)
from indexing import RememberberryDatabase
rbd = RememberberryDatabase('rb.db')

----------
2018-09-03
----------
It's clear that the summary statistics for sentences is not right.
When a note is updated, first we need to find all note_links for that note.
Then for each note in the links, we need to recalculate the reps,lapses for the whole item with the reps,lapses from the max score. Then for each parent item, need to
add the difference

Or use median instead of mean

----------
2018-09-04
----------
Decided to just recalculate an item completely in a child changed, shouldn't be
too slow. So if a note changed, then update all items that point to that note.
For each item that was updated, update their parents as well, keep the sum of
reps-lapses, and the total count so we can get the average

----------
2018-09-23
----------
Use jieba for segmentation? The search function can return compounds as well as their
constituents. Have a few choices:
1. Set up compounds as their own type of item, use a different statistic query
   for them (minimum of all constituent max_correct)
   Use jieba on cedict to find all compounds
   Then use jieba without the search function on the sentences
