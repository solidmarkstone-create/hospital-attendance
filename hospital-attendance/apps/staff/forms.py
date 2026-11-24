from django import forms

from .models import Employee


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['personnel_number', 'last_name', 'first_name', 'middle_name', 'department', 'position',
                  'user', 'is_active']


class ConsentForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['consent', 'consent_date', 'consent_doc']
        widgets = {'consent_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def clean(self):
        data = super().clean()
        if data.get('consent') != Employee.Consent.NONE and not data.get('consent_date'):
            self.add_error('consent_date', 'Укажите дату согласия или отзыва.')
        if data.get('consent') == Employee.Consent.GIVEN and not data.get('consent_doc'):
            self.add_error('consent_doc', 'Укажите номер и дату письменного согласия.')
        return data


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    """Поле для нескольких файлов (рецепт из документации Django 5)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultiFileInput(attrs={'accept': 'image/jpeg,image/png'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return [single(data, initial)] if data else []


class EnrollForm(forms.Form):
    photos = MultiFileField(label='Фотографии (1–5 снимков анфас)', required=False)
    camera_frames = forms.CharField(widget=forms.HiddenInput, required=False)


class PinForm(forms.Form):
    pin = forms.RegexField(label='PIN запасной отметки (4–6 цифр)', regex=r'^\d{4,6}$',
                           widget=forms.PasswordInput(render_value=False))
