import django.forms
from django.views.generic.edit import CreateView as _CreateView, UpdateView as _UpdateView

from forms import transactional_save


class TransactionalModelFormMixin(object):
    def validationerror_from_integrityerror(self, ierror):
        return None

    def form_valid(self, form):
        try:
            convertors = [ lambda i: self.validationerror_from_integrityerror(i) ]
            if hasattr(form, "tsave"):
                self.object = form.tsave(convertors)
            else:
                self.object = transactional_save(form, convertors)
            return super(TransactionalModelFormMixin, self).form_valid(form)
        except django.forms.ValidationError:
            return self.form_invalid(form)


class CreateView(TransactionalModelFormMixin, _CreateView):
    pass


class UpdateView(TransactionalModelFormMixin, _UpdateView):
    pass
