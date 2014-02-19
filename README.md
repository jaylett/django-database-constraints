# django-database-constraints

Constraints and model invariants belong in your database, not in Django code. This means that we need Django-ish ways of using the database to do what people currently do by raising `ValidationError` in various places such as `Form`s, `Model`s and so forth.

## "But Django has [form, model] validation"

No, it *almost* has it; it lacks real concurrency facilities. Say I have the following:

    from django import models
    from django.views.generic import CreateView
    
    class MyModel(models.Model):
        order = models.IntegerField(unique=True)
    
    class CreateMyModel(CreateView):
        model = MyModel

What happens is that uniqueness is checked, then the object is created. If two requests try to create a `MyModel` with the same `order` at once, it's possible for the validation tests to pass in both requests *before* either one of them writes to the database. One request will succeed, and the other will throw an `IntegrityError`. This doesn't get caught anywhere in the normal forms and views infrastructure, so the second request will return HTTP 500. This isn't pleasant.

For other constraint validation, such as is commonly implemented in `clean_<FIELD>` on a `Form`, then you can land in an even worse case: if the validation passes in both requests then Django will happily write both objects to the database. Without constraints in the database you won't even get an `IntegrityError`; you'll just violate your model invariant. (At least with `unique=True` in field definitions this gets passed down to the database.)

Here's my rule of thumb about what code should go where, which isn't what you'd imagine from the Django documentation:

 * if you need to alter incoming data before writing it to a `Model` field, use a `clean_<FIELD>` method on the `Form` (that's assuming you can't do it using a custom form field type or custom model field type)
 * put actual constraints in the database
 * never put constraints in `Model.clean()`

You shouldn't even put instance invariant checks in [`Model.clean()`](https://docs.djangoproject.com/en/dev/ref/models/instances/#django.db.models.Model.clean), although they won't be affected by concurrency issues, because if you want anything other than Django to be able to edit your database, ever, you should make invariants a part of the database schema. Similarly, defaults are often better off in your database than in Django (although depending on your database, introducing and changing defaults after the fact can take a long time).

## How do we address this?

There are a couple of problems:

 * you can't raise `ValidationError` from a form's `.save()` method and have it do anything sensible
 * you don't want to have to catch every `IntegrityError` by hand and convert it into a `ValidationError`

`ValidationError` is a good thing and integrates fairly well into the existing forms system -- particularly displaying forms that fail validation -- and `IntegrityError` is a fairly low level database-level thing, so we want to convert the latter into the former.

This extension therefore provides:

 * a mechanism for converting  `IntegrityError` exceptions into `ValidationError` instances instead
 * an overridable system for attributing the original exception to a specific form field
 * a mixin for a `FormView` (most likely `CreateView` and `UpdateView`, for which there are convenience replacements) which uses the conversion mechanism and then catches `ValidationError` on `.save()` adding it as an error to the form, against the relevant form field

## Notes about transactions

Although the code will take care of this for you if you're only doing very basic work, it's a good plan to wrap the `.save()` method of your `Form` or `ModelForm` in a transaction. You can do this easily in three ways, in increasing order of desirability:

 * set `ATOMIC_REQUESTS=True` in `settings.py`, wrapping every request in a transaction
 * decorate all database modifying views with `transaction.atomic()` (for instance in `urls.py`)
 * decorate just the `.save()` method (or wrap all code within it in a `with` statement) with `transaction.atomic()`

Lower on the list is better because it means less of your application lives within a database transaction (which will often be better in terms of both performance and scalability), but comes at a cost of having to think more about the moving parts of your system.

However you don't always need to bother because:

 * if you use the view mixin then it will wrap the actual `.save()` in an atomic transaction (as well as doing the `IntegrityError` to `ValidationError` conversion and using the `ValidationError` as a form error)
 * if you use the `TransactionalMixin` with your forms then you get a `.tsave()` method which does all of the above; there's also a convenience `ModelForm` that pulls that into Django's usual one

So you only need to worry about `.save()` if it's going to be called *on your form* by some other code that isn't under your control (where you could use `.tsave()`).

Separately if you have code that calls `.save()` on your model directly then you probably want to do something similar. You can use the `IntegrityError`-to-`ValidationError` stuff (`django_database_constraints.forms.validationerror_from_integrityerror`) to do the conversion, and the rest is fairly straightforward:

    class TransactionalModelMixin(object):
        def tsave(self):
            try:
                with transaction.atomic():
                    return self.save()
            except IntegrityError as e:
                raise validationerror_from_integrityerror(e)

(This isn't provided as a convenience mixin simply because I haven't gotten round to writing tests for it. Tests are really important for this kind of extension.)

## So how do I use it?

Instead of this:

    from django import models
    from django.views.generic import CreateView
    
    class MyModel(models.Model):
        order = models.IntegerField(unique=True)
    
    class CreateMyModel(CreateView):
        model = MyModel

Try this:

    from django import models
    from django.views.generic import CreateView
    from django_database_constraints.views import TransactionalModelFormMixin
    
    class MyModel(models.Model):
        order = models.IntegerField(unique=True)
    
    class CreateMyModel(TransactionalModelFormMixin, CreateView):
        model = MyModel

Or just this:

    from django import models
    from django_database_constraints.views import CreateView
    
    class MyModel(models.Model):
        order = models.IntegerField(unique=True)
    
    class CreateMyModel(CreateView):
        model = MyModel

The same works with `UpdateView`. If you bring in `django_database_constraints.forms.TransactionalMixin` to your forms then you get `.tsave()` on them which does all the conversion and adding `ValidationError` as a form error stuff; this method will be called in preference by the `TransactionalModelFormMixin` so you can override its behaviour if you really need to.

If you want to provide custom code to convert from an `IntegrityError` to a `ValidationError` then override `.validationerror_from_integrityerror()` on your form processing view (the one that has `TransactionalModelFormMixin`). Note that to create a `ValidationError` for a particular field you construct it with a dictionary:

    raise ValidationError({ 'fieldname': ['validation message']})

## Managing the database transaction

There's a `tx_context_manager` parameter to `transactional_save`, which is intended to allow use with `django-ballads`, another of my extensions which allows you to register compensating transactions to clean up non-database operations (eg external payment processing) on transaction rollback. (In theory you could come up with your own context manager instead, which might be useful in some very specific situations.)

Consider a `Form` which you want to work with database-level constraints (perhaps a unique email address on account creation) and external services (say, charging via an external payment provider). You want to do something like this:

    class CreateForm(forms.Form):
        email = EmailField()
        # ... other fields

        def tsave(self, convertors=None):
            self.ballad = Ballad()
            return transactional_save(self, convertors, self.ballad)

        def save(self):
            # Note that this runs inside the ballad (which itself contains
            # a database transaction using `transaction.atomic`). This is
            # better than declaring a ballad in this method because you
            # won't necessarily get every possible `IntegrityError` out
            # of the database until the outer transaction is committed, so
            # you could leak a charge.
            user = User.objects.create(
                email = self.cleaned_data['email'],
                # ... other fields
            )
            charge = external_provider.Charge.create(
                # payment fields
            )
            self.ballad.compensation(lambda: charge.refund())
            # maybe also subscribe to mailing lists &c
            return user

Remember that in a ballad, the database transaction is rolled back before any of the compensating transactions are run.

## Future work

It should be possible to automatically ascribe the vast majority of integrity failures to specific fields both for mysql and postgresql. Getting helpful error messages is going to be hard in the general case.

I'd like to have a function that will auto-patch the admin, so it will be safe as well.

## Requirements

Django 1.6, for the new transaction work.

A modern relational database: the test harness runs against both postgresql and mysql. sqlite3 may work, but I can't test it because it doesn't like threading (which I'm using to test concurrency).

## Developing

You want the following to be able to work on the code and run the tests:

    $ pip install Django>=1.6.0 coverage psycopg2 MySQL-python

Note that if you use the official distributions of MySQL on Mac OS you want to run this with `PATH=$PATH:/usr/local/mysql/bin` and run `make coverage` with DYLD_LIBRARY_PATH=/usr/local/mysql/lib`. (Use `Postgresql.app` for convenience.)

## License

MIT license; [source is on github][Package source].

## Contact

This is very early days for this; feedback welcome.

[James Aylett][James' homepage]

  [James' homepage]: http://tartarus.org/james/
  [Package source]: https://github.com/jaylett/django-database-constraints
