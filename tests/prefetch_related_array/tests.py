from __future__ import unicode_literals

import warnings

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.db.models import Prefetch
from django.db.models.query import get_prefetcher
from django.test import TestCase, override_settings
from django.utils import six
from django.utils.encoding import force_str
from unittest import skip

from .models import (
    Author, Author2, AuthorAddress, AuthorWithAge, Bio, Book, Bookmark,
    BookReview, BookWithYear, Comment, Department, Employee,
    House, LessonEntry, Person, Qualification, Reader, Room, TaggedItem,
    Teacher, WordEntry,
)



class PrefetchRelatedTests(TestCase):
    def setUp(self):
        self.book1 = Book.objects.create(title="Poems")
        self.book2 = Book.objects.create(title="Jane Eyre")
        self.book3 = Book.objects.create(title="Wuthering Heights")
        self.book4 = Book.objects.create(title="Sense and Sensibility")

        self.author1 = Author.objects.create(name="Charlotte",
                                             first_book=self.book1)
        self.author2 = Author.objects.create(name="Anne",
                                             first_book=self.book1)
        self.author3 = Author.objects.create(name="Emily",
                                             first_book=self.book1)
        self.author4 = Author.objects.create(name="Jane",
                                             first_book=self.book4)

        self.book1.authors.add(self.author1, self.author2, self.author3)
        self.book2.authors.add(self.author1)
        self.book3.authors.add(self.author3)
        self.book4.authors.add(self.author4)

        self.reader1 = Reader.objects.create(name="Amy")
        self.reader2 = Reader.objects.create(name="Belinda")

        self.reader1.books_read.add(self.book1, self.book4)
        self.reader2.books_read.add(self.book2, self.book4)

    def test_m2m_forward(self):
        with self.assertNumQueries(2):
            lists = [list(b.authors.all()) for b in Book.objects.prefetch_related('authors')]

        normal_lists = [list(b.authors.all()) for b in Book.objects.all()]
        self.assertEqual(lists, normal_lists)

    def test_m2m_reverse(self):
        with self.assertNumQueries(2):
            lists = [list(a.books.all()) for a in Author.objects.prefetch_related('books')]

        normal_lists = [list(a.books.all()) for a in Author.objects.all()]
        self.assertEqual(lists, normal_lists)

    def test_foreignkey_forward(self):
        with self.assertNumQueries(2):
            books = [a.first_book for a in Author.objects.prefetch_related('first_book')]

        normal_books = [a.first_book for a in Author.objects.all()]
        self.assertEqual(books, normal_books)

    def test_foreignkey_reverse(self):
        with self.assertNumQueries(2):
            [list(b.first_time_authors.all())
             for b in Book.objects.prefetch_related('first_time_authors')]

        self.assertQuerysetEqual(self.book2.authors.all(), ["<Author: Charlotte>"])

    def test_onetoone_reverse_no_match(self):
        # Regression for #17439
        with self.assertNumQueries(2):
            book = Book.objects.prefetch_related('bookwithyear').all()[0]
        with self.assertNumQueries(0):
            with self.assertRaises(BookWithYear.DoesNotExist):
                book.bookwithyear

    def test_survives_clone(self):
        with self.assertNumQueries(2):
            [list(b.first_time_authors.all())
             for b in Book.objects.prefetch_related('first_time_authors').exclude(id=1000)]

    def test_len(self):
        with self.assertNumQueries(2):
            qs = Book.objects.prefetch_related('first_time_authors')
            len(qs)
            [list(b.first_time_authors.all()) for b in qs]

    def test_bool(self):
        with self.assertNumQueries(2):
            qs = Book.objects.prefetch_related('first_time_authors')
            bool(qs)
            [list(b.first_time_authors.all()) for b in qs]

    def test_count(self):
        with self.assertNumQueries(2):
            qs = Book.objects.prefetch_related('first_time_authors')
            [b.first_time_authors.count() for b in qs]

    def test_exists(self):
        with self.assertNumQueries(2):
            qs = Book.objects.prefetch_related('first_time_authors')
            [b.first_time_authors.exists() for b in qs]

    def test_in_and_prefetch_related(self):
        """
        Regression test for #20242 - QuerySet "in" didn't work the first time
        when using prefetch_related. This was fixed by the removal of chunked
        reads from QuerySet iteration in
        70679243d1786e03557c28929f9762a119e3ac14.
        """
        qs = Book.objects.prefetch_related('first_time_authors')
        self.assertIn(qs[0], qs)

    def test_clear(self):
        """
        Test that we can clear the behavior by calling prefetch_related()
        """
        with self.assertNumQueries(5):
            with_prefetch = Author.objects.prefetch_related('books')
            without_prefetch = with_prefetch.prefetch_related(None)
            [list(a.books.all()) for a in without_prefetch]

    def test_m2m_then_m2m(self):
        """
        Test we can follow a m2m and another m2m
        """
        with self.assertNumQueries(3):
            qs = Author.objects.prefetch_related('books__read_by')
            lists = [[[six.text_type(r) for r in b.read_by.all()]
                      for b in a.books.all()]
                     for a in qs]
            self.assertEqual(lists,
            [
                [["Amy"], ["Belinda"]],  # Charlotte - Poems, Jane Eyre
                [["Amy"]],                # Anne - Poems
                [["Amy"], []],            # Emily - Poems, Wuthering Heights
                [["Amy", "Belinda"]],    # Jane - Sense and Sense
            ])

    def test_overriding_prefetch(self):
        with self.assertNumQueries(3):
            qs = Author.objects.prefetch_related('books', 'books__read_by')
            lists = [[[six.text_type(r) for r in b.read_by.all()]
                      for b in a.books.all()]
                     for a in qs]
            self.assertEqual(lists,
            [
                [["Amy"], ["Belinda"]],  # Charlotte - Poems, Jane Eyre
                [["Amy"]],                # Anne - Poems
                [["Amy"], []],            # Emily - Poems, Wuthering Heights
                [["Amy", "Belinda"]],    # Jane - Sense and Sense
            ])
        with self.assertNumQueries(3):
            qs = Author.objects.prefetch_related('books__read_by', 'books')
            lists = [[[six.text_type(r) for r in b.read_by.all()]
                      for b in a.books.all()]
                     for a in qs]
            self.assertEqual(lists,
            [
                [["Amy"], ["Belinda"]],  # Charlotte - Poems, Jane Eyre
                [["Amy"]],                # Anne - Poems
                [["Amy"], []],            # Emily - Poems, Wuthering Heights
                [["Amy", "Belinda"]],    # Jane - Sense and Sense
            ])

    def test_get(self):
        """
        Test that objects retrieved with .get() get the prefetch behavior.
        """
        # Need a double
        with self.assertNumQueries(3):
            author = Author.objects.prefetch_related('books__read_by').get(name="Charlotte")
            lists = [[six.text_type(r) for r in b.read_by.all()]
                     for b in author.books.all()]
            self.assertEqual(lists, [["Amy"], ["Belinda"]])  # Poems, Jane Eyre

    def test_foreign_key_then_m2m(self):
        """
        Test we can follow an m2m relation after a relation like ForeignKey
        that doesn't have many objects
        """
        with self.assertNumQueries(2):
            qs = Author.objects.select_related('first_book').prefetch_related('first_book__read_by')
            lists = [[six.text_type(r) for r in a.first_book.read_by.all()]
                     for a in qs]
            self.assertEqual(lists, [["Amy"],
                                     ["Amy"],
                                     ["Amy"],
                                     ["Amy", "Belinda"]])

    def test_reverse_one_to_one_then_m2m(self):
        """
        Test that we can follow a m2m relation after going through
        the select_related reverse of an o2o.
        """
        qs = Author.objects.prefetch_related('bio__books').select_related('bio')

        with self.assertNumQueries(1):
            list(qs.all())

        bio = Bio.objects.create(author=self.author1)
        bio.books.set([self.book1, self.book2])
        with self.assertNumQueries(2):
            objs = list(qs.all())
            for obj in objs:
                if obj.pk == self.author1.pk:
                    self.assertEqual(obj.bio.pk, bio.pk)
                    self.assertQuerysetEqual(obj.bio.books.all(), ['<Book: Poems>', '<Book: Jane Eyre>'])

    def test_attribute_error(self):
        qs = Reader.objects.all().prefetch_related('books_read__xyz')
        with self.assertRaises(AttributeError) as cm:
            list(qs)

        self.assertIn('prefetch_related', str(cm.exception))

    def test_invalid_final_lookup(self):
        qs = Book.objects.prefetch_related('authors__name')
        with self.assertRaises(ValueError) as cm:
            list(qs)

        self.assertIn('prefetch_related', str(cm.exception))
        self.assertIn("name", str(cm.exception))

    def test_forward_m2m_to_attr_conflict(self):
        msg = 'to_attr=authors conflicts with a field on the Book model.'
        authors = Author.objects.all()
        with self.assertRaisesMessage(ValueError, msg):
            list(Book.objects.prefetch_related(
                Prefetch('authors', queryset=authors, to_attr='authors'),
            ))
        # Without the ValueError, an author was deleted due to the implicit
        # save of the relation assignment.
        self.assertEqual(self.book1.authors.count(), 3)

    def test_reverse_m2m_to_attr_conflict(self):
        msg = 'to_attr=books conflicts with a field on the Author model.'
        poems = Book.objects.filter(title='Poems')
        with self.assertRaisesMessage(ValueError, msg):
            list(Author.objects.prefetch_related(
                Prefetch('books', queryset=poems, to_attr='books'),
            ))
        # Without the ValueError, a book was deleted due to the implicit
        # save of reverse relation assignment.
        self.assertEqual(self.author1.books.count(), 2)


class CustomPrefetchTests(TestCase):
    @classmethod
    def traverse_qs(cls, obj_iter, path):
        """
        Helper method that returns a list containing a list of the objects in the
        obj_iter. Then for each object in the obj_iter, the path will be
        recursively travelled and the found objects are added to the return value.
        """
        ret_val = []

        if hasattr(obj_iter, 'all'):
            obj_iter = obj_iter.all()

        try:
            iter(obj_iter)
        except TypeError:
            obj_iter = [obj_iter]

        for obj in obj_iter:
            rel_objs = []
            for part in path:
                if not part:
                    continue
                try:
                    related = getattr(obj, part[0])
                except ObjectDoesNotExist:
                    continue
                if related is not None:
                    rel_objs.extend(cls.traverse_qs(related, [part[1:]]))
            ret_val.append((obj, rel_objs))
        return ret_val

    def setUp(self):
        self.person1 = Person.objects.create(name="Joe")
        self.person2 = Person.objects.create(name="Mary")

        # Set main_room for each house before creating the next one for
        # databases where supports_nullable_unique_constraints is False.

        self.house1 = House.objects.create(name='House 1', address="123 Main St", owner=self.person1)
        self.room1_1 = Room.objects.create(name="Dining room", house=self.house1)
        self.room1_2 = Room.objects.create(name="Lounge", house=self.house1)
        self.room1_3 = Room.objects.create(name="Kitchen", house=self.house1)
        self.house1.main_room = self.room1_1
        self.house1.save()
        self.person1.houses.add(self.house1)

        self.house2 = House.objects.create(name='House 2', address="45 Side St", owner=self.person1)
        self.room2_1 = Room.objects.create(name="Dining room", house=self.house2)
        self.room2_2 = Room.objects.create(name="Lounge", house=self.house2)
        self.room2_3 = Room.objects.create(name="Kitchen", house=self.house2)
        self.house2.main_room = self.room2_1
        self.house2.save()
        self.person1.houses.add(self.house2)

        self.house3 = House.objects.create(name='House 3', address="6 Downing St", owner=self.person2)
        self.room3_1 = Room.objects.create(name="Dining room", house=self.house3)
        self.room3_2 = Room.objects.create(name="Lounge", house=self.house3)
        self.room3_3 = Room.objects.create(name="Kitchen", house=self.house3)
        self.house3.main_room = self.room3_1
        self.house3.save()
        self.person2.houses.add(self.house3)

        self.house4 = House.objects.create(name='house 4', address="7 Regents St", owner=self.person2)
        self.room4_1 = Room.objects.create(name="Dining room", house=self.house4)
        self.room4_2 = Room.objects.create(name="Lounge", house=self.house4)
        self.room4_3 = Room.objects.create(name="Kitchen", house=self.house4)
        self.house4.main_room = self.room4_1
        self.house4.save()
        self.person2.houses.add(self.house4)

    def test_traverse_qs(self):
        qs = Person.objects.prefetch_related('houses')
        related_objs_normal = [list(p.houses.all()) for p in qs],
        related_objs_from_traverse = [[inner[0] for inner in o[1]]
                                      for o in self.traverse_qs(qs, [['houses']])]
        self.assertEqual(related_objs_normal, (related_objs_from_traverse,))

    def test_ambiguous(self):
        # Ambiguous: Lookup was already seen with a different queryset.
        with self.assertRaises(ValueError):
            self.traverse_qs(
                Person.objects.prefetch_related('houses__rooms', Prefetch('houses', queryset=House.objects.all())),
                [['houses', 'rooms']]
            )

        # Ambiguous: Lookup houses_lst doesn't yet exist when performing houses_lst__rooms.
        with self.assertRaises(AttributeError):
            self.traverse_qs(
                Person.objects.prefetch_related(
                    'houses_lst__rooms',
                    Prefetch('houses', queryset=House.objects.all(), to_attr='houses_lst')
                ),
                [['houses', 'rooms']]
            )

        # Not ambiguous.
        self.traverse_qs(
            Person.objects.prefetch_related('houses__rooms', 'houses'),
            [['houses', 'rooms']]
        )

        self.traverse_qs(
            Person.objects.prefetch_related(
                'houses__rooms',
                Prefetch('houses', queryset=House.objects.all(), to_attr='houses_lst')
            ),
            [['houses', 'rooms']]
        )

    def test_m2m(self):
        # Control lookups.
        with self.assertNumQueries(2):
            lst1 = self.traverse_qs(
                Person.objects.prefetch_related('houses'),
                [['houses']]
            )

        # Test lookups.
        with self.assertNumQueries(2):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(Prefetch('houses')),
                [['houses']]
            )
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(2):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(Prefetch('houses', to_attr='houses_lst')),
                [['houses_lst']]
            )
        self.assertEqual(lst1, lst2)

    def test_reverse_m2m(self):
        # Control lookups.
        with self.assertNumQueries(2):
            lst1 = self.traverse_qs(
                House.objects.prefetch_related('occupants'),
                [['occupants']]
            )

        # Test lookups.
        with self.assertNumQueries(2):
            lst2 = self.traverse_qs(
                House.objects.prefetch_related(Prefetch('occupants')),
                [['occupants']]
            )
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(2):
            lst2 = self.traverse_qs(
                House.objects.prefetch_related(Prefetch('occupants', to_attr='occupants_lst')),
                [['occupants_lst']]
            )
        self.assertEqual(lst1, lst2)

    def test_m2m_through_fk(self):
        # Control lookups.
        with self.assertNumQueries(3):
            lst1 = self.traverse_qs(
                Room.objects.prefetch_related('house__occupants'),
                [['house', 'occupants']]
            )

        # Test lookups.
        with self.assertNumQueries(3):
            lst2 = self.traverse_qs(
                Room.objects.prefetch_related(Prefetch('house__occupants')),
                [['house', 'occupants']]
            )
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(3):
            lst2 = self.traverse_qs(
                Room.objects.prefetch_related(Prefetch('house__occupants', to_attr='occupants_lst')),
                [['house', 'occupants_lst']]
            )
        self.assertEqual(lst1, lst2)

    def test_m2m_through_gfk(self):
        TaggedItem.objects.create(tag="houses", content_object=self.house1)
        TaggedItem.objects.create(tag="houses", content_object=self.house2)

        # Control lookups.
        with self.assertNumQueries(3):
            lst1 = self.traverse_qs(
                TaggedItem.objects.filter(tag='houses').prefetch_related('content_object__rooms'),
                [['content_object', 'rooms']]
            )

        # Test lookups.
        with self.assertNumQueries(3):
            lst2 = self.traverse_qs(
                TaggedItem.objects.prefetch_related(
                    Prefetch('content_object'),
                    Prefetch('content_object__rooms', to_attr='rooms_lst')
                ),
                [['content_object', 'rooms_lst']]
            )
        self.assertEqual(lst1, lst2)

    def test_o2m_through_m2m(self):
        # Control lookups.
        with self.assertNumQueries(3):
            lst1 = self.traverse_qs(
                Person.objects.prefetch_related('houses', 'houses__rooms'),
                [['houses', 'rooms']]
            )

        # Test lookups.
        with self.assertNumQueries(3):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(Prefetch('houses'), 'houses__rooms'),
                [['houses', 'rooms']]
            )
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(3):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(Prefetch('houses'), Prefetch('houses__rooms')),
                [['houses', 'rooms']]
            )
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(3):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(Prefetch('houses', to_attr='houses_lst'), 'houses_lst__rooms'),
                [['houses_lst', 'rooms']]
            )
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(3):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(
                    Prefetch('houses', to_attr='houses_lst'),
                    Prefetch('houses_lst__rooms', to_attr='rooms_lst')
                ),
                [['houses_lst', 'rooms_lst']]
            )
        self.assertEqual(lst1, lst2)

    def test_generic_rel(self):
        bookmark = Bookmark.objects.create(url='http://www.djangoproject.com/')
        TaggedItem.objects.create(content_object=bookmark, tag='django')
        TaggedItem.objects.create(content_object=bookmark, favorite=bookmark, tag='python')

        # Control lookups.
        with self.assertNumQueries(4):
            lst1 = self.traverse_qs(
                Bookmark.objects.prefetch_related('tags', 'tags__content_object', 'favorite_tags'),
                [['tags', 'content_object'], ['favorite_tags']]
            )

        # Test lookups.
        with self.assertNumQueries(4):
            lst2 = self.traverse_qs(
                Bookmark.objects.prefetch_related(
                    Prefetch('tags', to_attr='tags_lst'),
                    Prefetch('tags_lst__content_object'),
                    Prefetch('favorite_tags'),
                ),
                [['tags_lst', 'content_object'], ['favorite_tags']]
            )
        self.assertEqual(lst1, lst2)

    def test_traverse_single_item_property(self):
        # Control lookups.
        with self.assertNumQueries(5):
            lst1 = self.traverse_qs(
                Person.objects.prefetch_related(
                    'houses__rooms',
                    'primary_house__occupants__houses',
                ),
                [['primary_house', 'occupants', 'houses']]
            )

        # Test lookups.
        with self.assertNumQueries(5):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(
                    'houses__rooms',
                    Prefetch('primary_house__occupants', to_attr='occupants_lst'),
                    'primary_house__occupants_lst__houses',
                ),
                [['primary_house', 'occupants_lst', 'houses']]
            )
        self.assertEqual(lst1, lst2)

    def test_traverse_multiple_items_property(self):
        # Control lookups.
        with self.assertNumQueries(4):
            lst1 = self.traverse_qs(
                Person.objects.prefetch_related(
                    'houses',
                    'all_houses__occupants__houses',
                ),
                [['all_houses', 'occupants', 'houses']]
            )

        # Test lookups.
        with self.assertNumQueries(4):
            lst2 = self.traverse_qs(
                Person.objects.prefetch_related(
                    'houses',
                    Prefetch('all_houses__occupants', to_attr='occupants_lst'),
                    'all_houses__occupants_lst__houses',
                ),
                [['all_houses', 'occupants_lst', 'houses']]
            )
        self.assertEqual(lst1, lst2)

    def test_custom_qs(self):
        # Test basic.
        with self.assertNumQueries(2):
            lst1 = list(Person.objects.prefetch_related('houses'))
        with self.assertNumQueries(2):
            lst2 = list(Person.objects.prefetch_related(
                Prefetch('houses', queryset=House.objects.all(), to_attr='houses_lst')))
        self.assertEqual(
            self.traverse_qs(lst1, [['houses']]),
            self.traverse_qs(lst2, [['houses_lst']])
        )

        # Test queryset filtering.
        with self.assertNumQueries(2):
            lst2 = list(
                Person.objects.prefetch_related(
                    Prefetch(
                        'houses',
                        queryset=House.objects.filter(pk__in=[self.house1.pk, self.house3.pk]),
                        to_attr='houses_lst',
                    )
                )
            )
        self.assertEqual(len(lst2[0].houses_lst), 1)
        self.assertEqual(lst2[0].houses_lst[0], self.house1)
        self.assertEqual(len(lst2[1].houses_lst), 1)
        self.assertEqual(lst2[1].houses_lst[0], self.house3)

        # Test flattened.
        with self.assertNumQueries(3):
            lst1 = list(Person.objects.prefetch_related('houses__rooms'))
        with self.assertNumQueries(3):
            lst2 = list(Person.objects.prefetch_related(
                Prefetch('houses__rooms', queryset=Room.objects.all(), to_attr='rooms_lst')))
        self.assertEqual(
            self.traverse_qs(lst1, [['houses', 'rooms']]),
            self.traverse_qs(lst2, [['houses', 'rooms_lst']])
        )

        # Test inner select_related.
        with self.assertNumQueries(3):
            lst1 = list(Person.objects.prefetch_related('houses__owner'))
        with self.assertNumQueries(2):
            lst2 = list(Person.objects.prefetch_related(
                Prefetch('houses', queryset=House.objects.select_related('owner'))))
        self.assertEqual(
            self.traverse_qs(lst1, [['houses', 'owner']]),
            self.traverse_qs(lst2, [['houses', 'owner']])
        )

        # Test inner prefetch.
        inner_rooms_qs = Room.objects.filter(pk__in=[self.room1_1.pk, self.room1_2.pk])
        houses_qs_prf = House.objects.prefetch_related(
            Prefetch('rooms', queryset=inner_rooms_qs, to_attr='rooms_lst'))
        with self.assertNumQueries(4):
            lst2 = list(Person.objects.prefetch_related(
                Prefetch('houses', queryset=houses_qs_prf.filter(pk=self.house1.pk), to_attr='houses_lst'),
                Prefetch('houses_lst__rooms_lst__main_room_of')
            ))

        self.assertEqual(len(lst2[0].houses_lst[0].rooms_lst), 2)
        self.assertEqual(lst2[0].houses_lst[0].rooms_lst[0], self.room1_1)
        self.assertEqual(lst2[0].houses_lst[0].rooms_lst[1], self.room1_2)
        self.assertEqual(lst2[0].houses_lst[0].rooms_lst[0].main_room_of, self.house1)
        self.assertEqual(len(lst2[1].houses_lst), 0)

        # Test ForwardManyToOneDescriptor.
        houses = House.objects.select_related('owner')
        with self.assertNumQueries(6):
            rooms = Room.objects.all().prefetch_related('house')
            lst1 = self.traverse_qs(rooms, [['house', 'owner']])
        with self.assertNumQueries(2):
            rooms = Room.objects.all().prefetch_related(Prefetch('house', queryset=houses.all()))
            lst2 = self.traverse_qs(rooms, [['house', 'owner']])
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(2):
            houses = House.objects.select_related('owner')
            rooms = Room.objects.all().prefetch_related(Prefetch('house', queryset=houses.all(), to_attr='house_attr'))
            lst2 = self.traverse_qs(rooms, [['house_attr', 'owner']])
        self.assertEqual(lst1, lst2)
        room = Room.objects.all().prefetch_related(
            Prefetch('house', queryset=houses.filter(address='DoesNotExist'))
        ).first()
        with self.assertRaises(ObjectDoesNotExist):
            getattr(room, 'house')
        room = Room.objects.all().prefetch_related(
            Prefetch('house', queryset=houses.filter(address='DoesNotExist'), to_attr='house_attr')
        ).first()
        self.assertIsNone(room.house_attr)
        rooms = Room.objects.all().prefetch_related(Prefetch('house', queryset=House.objects.only('name')))
        with self.assertNumQueries(2):
            getattr(rooms.first().house, 'name')
        with self.assertNumQueries(3):
            getattr(rooms.first().house, 'address')

        # Test ReverseOneToOneDescriptor.
        houses = House.objects.select_related('owner')
        with self.assertNumQueries(6):
            rooms = Room.objects.all().prefetch_related('main_room_of')
            lst1 = self.traverse_qs(rooms, [['main_room_of', 'owner']])
        with self.assertNumQueries(2):
            rooms = Room.objects.all().prefetch_related(Prefetch('main_room_of', queryset=houses.all()))
            lst2 = self.traverse_qs(rooms, [['main_room_of', 'owner']])
        self.assertEqual(lst1, lst2)
        with self.assertNumQueries(2):
            rooms = list(
                Room.objects.all().prefetch_related(
                    Prefetch('main_room_of', queryset=houses.all(), to_attr='main_room_of_attr')
                )
            )
            lst2 = self.traverse_qs(rooms, [['main_room_of_attr', 'owner']])
        self.assertEqual(lst1, lst2)
        room = Room.objects.filter(main_room_of__isnull=False).prefetch_related(
            Prefetch('main_room_of', queryset=houses.filter(address='DoesNotExist'))
        ).first()
        with self.assertRaises(ObjectDoesNotExist):
            getattr(room, 'main_room_of')
        room = Room.objects.filter(main_room_of__isnull=False).prefetch_related(
            Prefetch('main_room_of', queryset=houses.filter(address='DoesNotExist'), to_attr='main_room_of_attr')
        ).first()
        self.assertIsNone(room.main_room_of_attr)

    def test_nested_prefetch_related_are_not_overwritten(self):
        # Regression test for #24873
        houses_2 = House.objects.prefetch_related(Prefetch('rooms'))
        persons = Person.objects.prefetch_related(Prefetch('houses', queryset=houses_2))
        houses = House.objects.prefetch_related(Prefetch('occupants', queryset=persons))
        list(houses)  # queryset must be evaluated once to reproduce the bug.
        self.assertEqual(
            houses.all()[0].occupants.all()[0].houses.all()[1].rooms.all()[0],
            self.room2_1
        )


class DefaultManagerTests(TestCase):

    def setUp(self):
        self.qual1 = Qualification.objects.create(name="BA")
        self.qual2 = Qualification.objects.create(name="BSci")
        self.qual3 = Qualification.objects.create(name="MA")
        self.qual4 = Qualification.objects.create(name="PhD")

        self.teacher1 = Teacher.objects.create(name="Mr Cleese")
        self.teacher2 = Teacher.objects.create(name="Mr Idle")
        self.teacher3 = Teacher.objects.create(name="Mr Chapman")

        self.teacher1.qualifications.add(self.qual1, self.qual2, self.qual3, self.qual4)
        self.teacher2.qualifications.add(self.qual1)
        self.teacher3.qualifications.add(self.qual2)

        self.dept1 = Department.objects.create(name="English")
        self.dept2 = Department.objects.create(name="Physics")

        self.dept1.teachers.add(self.teacher1, self.teacher2)
        self.dept2.teachers.add(self.teacher1, self.teacher3)

    def test_m2m_then_m2m(self):
        with self.assertNumQueries(3):
            # When we prefetch the teachers, and force the query, we don't want
            # the default manager on teachers to immediately get all the related
            # qualifications, since this will do one query per teacher.
            qs = Department.objects.prefetch_related('teachers')
            depts = "".join("%s department: %s\n" %
                            (dept.name, ", ".join(six.text_type(t) for t in dept.teachers.all()))
                            for dept in qs)

            self.assertEqual(depts,
                             "English department: Mr Cleese (BA, BSci, MA, PhD), Mr Idle (BA)\n"
                             "Physics department: Mr Cleese (BA, BSci, MA, PhD), Mr Chapman (BSci)\n")


class GenericRelationTests(TestCase):

    def setUp(self):
        book1 = Book.objects.create(title="Winnie the Pooh")
        book2 = Book.objects.create(title="Do you like green eggs and spam?")
        book3 = Book.objects.create(title="Three Men In A Boat")

        reader1 = Reader.objects.create(name="me")
        reader2 = Reader.objects.create(name="you")
        reader3 = Reader.objects.create(name="someone")

        book1.read_by.add(reader1, reader2)
        book2.read_by.add(reader2)
        book3.read_by.add(reader3)

        self.book1, self.book2, self.book3 = book1, book2, book3
        self.reader1, self.reader2, self.reader3 = reader1, reader2, reader3

    def test_prefetch_GFK(self):
        TaggedItem.objects.create(tag="awesome", content_object=self.book1)
        TaggedItem.objects.create(tag="great", content_object=self.reader1)
        TaggedItem.objects.create(tag="outstanding", content_object=self.book2)
        TaggedItem.objects.create(tag="amazing", content_object=self.reader3)

        # 1 for TaggedItem table, 1 for Book table, 1 for Reader table
        with self.assertNumQueries(3):
            qs = TaggedItem.objects.prefetch_related('content_object')
            list(qs)

    def test_prefetch_GFK_nonint_pk(self):
        Comment.objects.create(comment="awesome", content_object=self.book1)

        # 1 for Comment table, 1 for Book table
        with self.assertNumQueries(2):
            qs = Comment.objects.prefetch_related('content_object')
            [c.content_object for c in qs]

    def test_traverse_GFK(self):
        """
        Test that we can traverse a 'content_object' with prefetch_related() and
        get to related objects on the other side (assuming it is suitably
        filtered)
        """
        TaggedItem.objects.create(tag="awesome", content_object=self.book1)
        TaggedItem.objects.create(tag="awesome", content_object=self.book2)
        TaggedItem.objects.create(tag="awesome", content_object=self.book3)
        TaggedItem.objects.create(tag="awesome", content_object=self.reader1)
        TaggedItem.objects.create(tag="awesome", content_object=self.reader2)

        ct = ContentType.objects.get_for_model(Book)

        # We get 3 queries - 1 for main query, 1 for content_objects since they
        # all use the same table, and 1 for the 'read_by' relation.
        with self.assertNumQueries(3):
            # If we limit to books, we know that they will have 'read_by'
            # attributes, so the following makes sense:
            qs = TaggedItem.objects.filter(content_type=ct, tag='awesome').prefetch_related('content_object__read_by')
            readers_of_awesome_books = {r.name for tag in qs
                                        for r in tag.content_object.read_by.all()}
            self.assertEqual(readers_of_awesome_books, {"me", "you", "someone"})

    def test_nullable_GFK(self):
        TaggedItem.objects.create(tag="awesome", content_object=self.book1,
                                  created_by=self.reader1)
        TaggedItem.objects.create(tag="great", content_object=self.book2)
        TaggedItem.objects.create(tag="rubbish", content_object=self.book3)

        with self.assertNumQueries(2):
            result = [t.created_by for t in TaggedItem.objects.prefetch_related('created_by')]

        self.assertEqual(result,
                         [t.created_by for t in TaggedItem.objects.all()])

    def test_generic_relation(self):
        bookmark = Bookmark.objects.create(url='http://www.djangoproject.com/')
        TaggedItem.objects.create(content_object=bookmark, tag='django')
        TaggedItem.objects.create(content_object=bookmark, tag='python')

        with self.assertNumQueries(2):
            tags = [t.tag for b in Bookmark.objects.prefetch_related('tags')
                    for t in b.tags.all()]
            self.assertEqual(sorted(tags), ["django", "python"])

    def test_charfield_GFK(self):
        b = Bookmark.objects.create(url='http://www.djangoproject.com/')
        TaggedItem.objects.create(content_object=b, tag='django')
        TaggedItem.objects.create(content_object=b, favorite=b, tag='python')

        with self.assertNumQueries(3):
            bookmark = Bookmark.objects.filter(pk=b.pk).prefetch_related('tags', 'favorite_tags')[0]
            self.assertEqual(sorted([i.tag for i in bookmark.tags.all()]), ["django", "python"])
            self.assertEqual([i.tag for i in bookmark.favorite_tags.all()], ["python"])

@skip("Not working")
class MultiTableInheritanceTest(TestCase):

    def setUp(self):
        self.book1 = BookWithYear.objects.create(
            title="Poems", published_year=2010)
        self.book2 = BookWithYear.objects.create(
            title="More poems", published_year=2011)
        self.author1 = AuthorWithAge.objects.create(
            name='Jane', first_book=self.book1, age=50)
        self.author2 = AuthorWithAge.objects.create(
            name='Tom', first_book=self.book1, age=49)
        self.author3 = AuthorWithAge.objects.create(
            name='Robert', first_book=self.book2, age=48)
        self.authorAddress = AuthorAddress.objects.create(
            author=self.author1, address='SomeStreet 1')
        self.book2.aged_authors.add(self.author2, self.author3)
        self.br1 = BookReview.objects.create(
            book=self.book1, notes="review book1")
        self.br2 = BookReview.objects.create(
            book=self.book2, notes="review book2")

    def test_foreignkey(self):
        with self.assertNumQueries(2):
            qs = AuthorWithAge.objects.prefetch_related('addresses')
            addresses = [[six.text_type(address) for address in obj.addresses.all()]
                         for obj in qs]
        self.assertEqual(addresses, [[six.text_type(self.authorAddress)], [], []])

    def test_foreignkey_to_inherited(self):
        with self.assertNumQueries(2):
            qs = BookReview.objects.prefetch_related('book')
            titles = [obj.book.title for obj in qs]
        self.assertEqual(titles, ["Poems", "More poems"])

    def test_m2m_to_inheriting_model(self):
        qs = AuthorWithAge.objects.prefetch_related('books_with_year')
        with self.assertNumQueries(2):
            lst = [[six.text_type(book) for book in author.books_with_year.all()]
                   for author in qs]
        qs = AuthorWithAge.objects.all()
        lst2 = [[six.text_type(book) for book in author.books_with_year.all()]
                for author in qs]
        self.assertEqual(lst, lst2)

        qs = BookWithYear.objects.prefetch_related('aged_authors')
        with self.assertNumQueries(2):
            lst = [[six.text_type(author) for author in book.aged_authors.all()]
                   for book in qs]
        qs = BookWithYear.objects.all()
        lst2 = [[six.text_type(author) for author in book.aged_authors.all()]
               for book in qs]
        self.assertEqual(lst, lst2)

    def test_parent_link_prefetch(self):
        with self.assertNumQueries(2):
            [a.author for a in AuthorWithAge.objects.prefetch_related('author')]

    @override_settings(DEBUG=True)
    def test_child_link_prefetch(self):
        with self.assertNumQueries(2):
            l = [a.authorwithage for a in Author.objects.prefetch_related('authorwithage')]

        # Regression for #18090: the prefetching query must include an IN clause.
        # Note that on Oracle the table name is upper case in the generated SQL,
        # thus the .lower() call.
        self.assertIn('authorwithage', connection.queries[-1]['sql'].lower())
        self.assertIn(' IN ', connection.queries[-1]['sql'])

        self.assertEqual(l, [a.authorwithage for a in Author.objects.all()])


class ForeignKeyToFieldTest(TestCase):

    def setUp(self):
        self.book = Book.objects.create(title="Poems")
        self.author1 = Author.objects.create(name='Jane', first_book=self.book)
        self.author2 = Author.objects.create(name='Tom', first_book=self.book)
        self.author3 = Author.objects.create(name='Robert', first_book=self.book)
        self.authorAddress = AuthorAddress.objects.create(
            author=self.author1, address='SomeStreet 1'
        )
        self.author1.favorite_authors.add(self.author2)
        self.author2.favorite_authors.add(self.author3)
        self.author3.favorite_authors.add(self.author1)

    def test_foreignkey(self):
        with self.assertNumQueries(2):
            qs = Author.objects.prefetch_related('addresses')
            addresses = [[six.text_type(address) for address in obj.addresses.all()]
                         for obj in qs]
        self.assertEqual(addresses, [[six.text_type(self.authorAddress)], [], []])

    def test_m2m(self):
        with self.assertNumQueries(3):
            qs = Author.objects.all().prefetch_related('favorite_authors', 'favors_me')
            favorites = [(
                [six.text_type(i_like) for i_like in author.favorite_authors.all()],
                [six.text_type(likes_me) for likes_me in author.favors_me.all()]
            ) for author in qs]
            self.assertEqual(
                favorites,
                [
                    ([six.text_type(self.author2)], [six.text_type(self.author3)]),
                    ([six.text_type(self.author3)], [six.text_type(self.author1)]),
                    ([six.text_type(self.author1)], [six.text_type(self.author2)])
                ]
            )


class LookupOrderingTest(TestCase):
    """
    Test cases that demonstrate that ordering of lookups is important, and
    ensure it is preserved.
    """

    def setUp(self):
        self.person1 = Person.objects.create(name="Joe")
        self.person2 = Person.objects.create(name="Mary")

        # Set main_room for each house before creating the next one for
        # databases where supports_nullable_unique_constraints is False.

        self.house1 = House.objects.create(address="123 Main St")
        self.room1_1 = Room.objects.create(name="Dining room", house=self.house1)
        self.room1_2 = Room.objects.create(name="Lounge", house=self.house1)
        self.room1_3 = Room.objects.create(name="Kitchen", house=self.house1)
        self.house1.main_room = self.room1_1
        self.house1.save()
        self.person1.houses.add(self.house1)

        self.house2 = House.objects.create(address="45 Side St")
        self.room2_1 = Room.objects.create(name="Dining room", house=self.house2)
        self.room2_2 = Room.objects.create(name="Lounge", house=self.house2)
        self.house2.main_room = self.room2_1
        self.house2.save()
        self.person1.houses.add(self.house2)

        self.house3 = House.objects.create(address="6 Downing St")
        self.room3_1 = Room.objects.create(name="Dining room", house=self.house3)
        self.room3_2 = Room.objects.create(name="Lounge", house=self.house3)
        self.room3_3 = Room.objects.create(name="Kitchen", house=self.house3)
        self.house3.main_room = self.room3_1
        self.house3.save()
        self.person2.houses.add(self.house3)

        self.house4 = House.objects.create(address="7 Regents St")
        self.room4_1 = Room.objects.create(name="Dining room", house=self.house4)
        self.room4_2 = Room.objects.create(name="Lounge", house=self.house4)
        self.house4.main_room = self.room4_1
        self.house4.save()
        self.person2.houses.add(self.house4)

    def test_order(self):
        with self.assertNumQueries(4):
            # The following two queries must be done in the same order as written,
            # otherwise 'primary_house' will cause non-prefetched lookups
            qs = Person.objects.prefetch_related('houses__rooms',
                                                 'primary_house__occupants')
            [list(p.primary_house.occupants.all()) for p in qs]


class NullableTest(TestCase):

    def setUp(self):
        boss = Employee.objects.create(name="Peter")
        Employee.objects.create(name="Joe", boss=boss)
        Employee.objects.create(name="Angela", boss=boss)

    def test_traverse_nullable(self):
        # Because we use select_related() for 'boss', it doesn't need to be
        # prefetched, but we can still traverse it although it contains some nulls
        with self.assertNumQueries(2):
            qs = Employee.objects.select_related('boss').prefetch_related('boss__serfs')
            co_serfs = [list(e.boss.serfs.all()) if e.boss is not None else []
                        for e in qs]

        qs2 = Employee.objects.select_related('boss')
        co_serfs2 = [list(e.boss.serfs.all()) if e.boss is not None else [] for e in qs2]

        self.assertEqual(co_serfs, co_serfs2)

    def test_prefetch_nullable(self):
        # One for main employee, one for boss, one for serfs
        with self.assertNumQueries(3):
            qs = Employee.objects.prefetch_related('boss__serfs')
            co_serfs = [list(e.boss.serfs.all()) if e.boss is not None else []
                        for e in qs]

        qs2 = Employee.objects.all()
        co_serfs2 = [list(e.boss.serfs.all()) if e.boss is not None else [] for e in qs2]

        self.assertEqual(co_serfs, co_serfs2)

    def test_in_bulk(self):
        """
        In-bulk does correctly prefetch objects by not using .iterator()
        directly.
        """
        boss1 = Employee.objects.create(name="Peter")
        boss2 = Employee.objects.create(name="Jack")
        with self.assertNumQueries(2):
            # Check that prefetch is done and it does not cause any errors.
            bulk = Employee.objects.prefetch_related('serfs').in_bulk([boss1.pk, boss2.pk])
            for b in bulk.values():
                list(b.serfs.all())

class Ticket19607Tests(TestCase):

    def setUp(self):

        for id, name1, name2 in [
            (1, 'einfach', 'simple'),
            (2, 'schwierig', 'difficult'),
        ]:
            LessonEntry.objects.create(id=id, name1=name1, name2=name2)

        for id, lesson_entry_id, name in [
            (1, 1, 'einfach'),
            (2, 1, 'simple'),
            (3, 2, 'schwierig'),
            (4, 2, 'difficult'),
        ]:
            WordEntry.objects.create(id=id, lesson_entry_id=lesson_entry_id, name=name)

    def test_bug(self):
        list(WordEntry.objects.prefetch_related('lesson_entry', 'lesson_entry__wordentry_set'))


class Ticket21410Tests(TestCase):

    def setUp(self):
        self.book1 = Book.objects.create(title="Poems")
        self.book2 = Book.objects.create(title="Jane Eyre")
        self.book3 = Book.objects.create(title="Wuthering Heights")
        self.book4 = Book.objects.create(title="Sense and Sensibility")

        self.author1 = Author2.objects.create(name="Charlotte",
                                             first_book=self.book1)
        self.author2 = Author2.objects.create(name="Anne",
                                             first_book=self.book1)
        self.author3 = Author2.objects.create(name="Emily",
                                             first_book=self.book1)
        self.author4 = Author2.objects.create(name="Jane",
                                             first_book=self.book4)

        self.author1.favorite_books.add(self.book1, self.book2, self.book3)
        self.author2.favorite_books.add(self.book1)
        self.author3.favorite_books.add(self.book2)
        self.author4.favorite_books.add(self.book3)

    def test_bug(self):
        list(Author2.objects.prefetch_related('first_book', 'favorite_books'))


class Ticket21760Tests(TestCase):

    def setUp(self):
        self.rooms = []
        for _ in range(3):
            house = House.objects.create()
            for _ in range(3):
                self.rooms.append(Room.objects.create(house=house))
            # Set main_room for each house before creating the next one for
            # databases where supports_nullable_unique_constraints is False.
            house.main_room = self.rooms[-3]
            house.save()

    def test_bug(self):
        prefetcher = get_prefetcher(self.rooms[0], 'house', 'house')[0]
        queryset = prefetcher.get_prefetch_queryset(list(Room.objects.all()))[0]
        self.assertNotIn(' JOIN ', str(queryset.query))
