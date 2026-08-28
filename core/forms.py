# ==================== FORMS.PY ====================
from django import forms
from .models import Usuario, Modelo, Peca, Ficha, ItemFicha, RegistroProducao, ItemFichaPeca, Setor, Operador
from django.contrib.auth.forms import UserCreationForm
from django.db.models.functions import Length


# formulario pra CRIAR um usuario
class RegistroUsuarioForm(UserCreationForm):
    # Define explicitamente o ModelChoiceField para popular todos os setores
    setor = forms.ModelChoiceField(
        queryset=Setor.objects.all(),
        empty_label="Selecione um setor...",
        required=False, # Torna o campo opcional
        label="Setor"
    )

    class Meta:
        model = Usuario
        fields = ['username', 'tipo', 'setor']
        labels = {
            'tipo': 'Tipo de Perfil',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Estilização industrial e Bootstrap dos campos
        for field_name in ['setor', 'tipo']:
            if field_name in self.fields:
                self.fields[field_name].widget.attrs.update({'class': 'form-select'})

        # Aplica form-control nos demais campos de texto/senha
        for field_name, field in self.fields.items():
            if field_name not in ['setor', 'tipo']:
                field.widget.attrs.update({'class': 'form-control'})


class SetorForm(forms.ModelForm):
    class Meta:
        model = Setor
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Pesponto, Corte, Montagem'}),
        }

    def clean_nome(self):
        nome = self.cleaned_data.get('nome')
        return nome.upper() if nome else nome


class OperadorForm(forms.ModelForm):
    class Meta:
        model = Operador
        fields = ['nome', 'setor', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome completo do operador'}),
            'setor': forms.Select(attrs={'class': 'form-select'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_nome(self):
        nome = self.cleaned_data.get('nome')
        return nome.upper() if nome else nome

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtra apenas setores para exibição em ordem alfabética
        self.fields['setor'].queryset = Setor.objects.all().order_by('nome')


class ModeloForm(forms.ModelForm):
    class Meta:
        model = Modelo
        fields = ['numero', 'tempo_fabricacao', 'ativo']
        labels = {
            'numero': 'Número do modelo',
            'tempo_fabricacao': 'Tempo de fabricação (min)',
            'ativo': 'Modelo ativo',
        }
        widgets = {
            'numero': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ex: 710'
            }),
            'tempo_fabricacao': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'placeholder': 'Ex: 1.17'
            }),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PecaForm(forms.ModelForm):
    class Meta:
        model = Peca
        fields = ['modelo', 'nome', 'tempo_fabricacao']
        labels = {
            'modelo': 'Modelo',
            'nome': 'Nome da peça',
            'tempo_fabricacao': 'Tempo de fabricação (min)',
        }
        widgets = {
            'modelo': forms.Select(attrs={'class': 'form-select', 'id': 'id_modelo'}),
            'nome': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ex: Sola'
            }),
            'tempo_fabricacao': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'placeholder': 'Ex: 0.35',
                'id': 'id_tempo_fabricacao'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # só modelos ativos aparecem pra vincular peça nova
        self.fields['modelo'].queryset = Modelo.objects.filter(ativo=True).annotate(tamanho_numero=Length('numero')).order_by('tamanho_numero', 'numero')

    def clean_nome(self):
        nome = self.cleaned_data.get('nome')
        return nome.upper() if nome else nome
    
    def clean(self):
        cleaned_data = super().clean()
        modelo = cleaned_data.get('modelo')
        tempo = cleaned_data.get('tempo_fabricacao')

        if modelo and tempo and tempo > modelo.tempo_fabricacao:
            self.add_error(
                'tempo_fabricacao',
                f"Não pode passar do tempo do modelo ({modelo.tempo_fabricacao} min)."
            )
        return cleaned_data


class FichaForm(forms.ModelForm):
    tipo = forms.ChoiceField(
        choices=Ficha.Tipo.choices,
        widget=forms.RadioSelect,
        label='Tipo de ficha',
        initial=Ficha.Tipo.PADRAO,
    )

    class Meta:
        model = Ficha
        fields = ['tipo', 'operador']
        labels = {'tipo': 'Tipo de ficha'}
        widgets = {
            'tipo': forms.RadioSelect,
            'operador': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Base: apenas operadores ativos com prefetch do setor
        queryset = Operador.objects.filter(ativo=True).select_related('setor')

        # Se o usuário possui um setor vinculado (via FK), filtra pelo ID direto
        if user and user.setor_id:
            queryset = queryset.filter(setor_id=user.setor_id)

        self.fields['operador'].queryset = queryset
        self.fields['operador'].empty_label = "Selecione o operador do seu setor..."

        # Torna o campo explicitamente obrigatório no formulário
        self.fields['operador'].required = True
        self.fields['operador'].error_messages = {
            'required': 'Por favor, selecione o operador responsável antes de continuar.'
        }


class ItemFichaForm(forms.ModelForm):
    class Meta:
        model = ItemFicha
        fields = ['modelo', 'numeracao', 'quantidade_planejada']
        labels = {
            'modelo': 'Modelo',
            'numeracao': 'Numeração (Tamanho)',
            'quantidade_planejada': 'Quantidade a produzir',
        }
        widgets = {
            'modelo': forms.Select(attrs={'class': 'form-select'}),
            'numeracao': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 26,
                'max': 45,
                'placeholder': 'Ex: 40'
            }),
            'quantidade_planejada': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 1, 'placeholder': 'Ex: 500'
            }),
        }

    def __init__(self, *args, ficha=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ficha = ficha
        self.instance.ficha = ficha

        self.fields['modelo'].queryset = Modelo.objects.filter(ativo=True).annotate(tamanho_numero=Length('numero')).order_by('tamanho_numero', 'numero')

        # ficha padrão não usa quantidade — nem mostra o campo
        if ficha and ficha.tipo == Ficha.Tipo.PADRAO:
            self.fields['quantidade_planejada'].widget = forms.HiddenInput()
            self.fields['quantidade_planejada'].required = False

    def clean(self):
        cleaned_data = super().clean()
        modelo = cleaned_data.get('modelo')
        numeracao = cleaned_data.get('numeracao')
        quantidade = cleaned_data.get('quantidade_planejada')

        # Validação 1: Evita duplicar o mesmo MODELO com a mesma NUMERAÇÃO na ficha
        if self.ficha and modelo and numeracao:
            ja_existe = ItemFicha.objects.filter(
                ficha=self.ficha, 
                modelo=modelo, 
                numeracao=numeracao
            ).exclude(pk=self.instance.pk).exists()

            if ja_existe:
                self.add_error('numeracao', f"O modelo {modelo.numero} já foi adicionado com a numeração {numeracao} nesta ficha.")

        if self.ficha and self.ficha.tipo == Ficha.Tipo.NUMERADA:
            if not quantidade or quantidade <= 0:
                self.add_error('quantidade_planejada', "Informe quantos pares serão produzidos.")
        else:
            cleaned_data['quantidade_planejada'] = None

        return cleaned_data

    def save(self, commit=True):
        self.instance.ficha = self.ficha
        if self.ficha.tipo == Ficha.Tipo.PADRAO:
            self.instance.quantidade_planejada = None
        return super().save(commit=commit)


class ItemFichaPecaForm(forms.Form):
    item_ficha = forms.ModelChoiceField(queryset=ItemFicha.objects.none(), widget=forms.HiddenInput())
    peca = forms.ModelChoiceField(queryset=Peca.objects.none())
    quantidade_planejada = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm mono',
            'placeholder': 'Qtd. Plan'
        })
    )

    def __init__(self, *args, ficha=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ficha = ficha
        if ficha:
            self.fields['item_ficha'].queryset = ficha.itens.all()
            modelo_ids = ficha.itens.values_list('modelo_id', flat=True)
            self.fields['peca'].queryset = Peca.objects.filter(modelo_id__in=modelo_ids)

    def clean(self):
        cleaned_data = super().clean()
        item_ficha = cleaned_data.get('item_ficha')
        peca = cleaned_data.get('peca')
        quantidade_planejada = cleaned_data.get('quantidade_planejada')

        if item_ficha and peca:
            if peca.modelo_id != item_ficha.modelo_id:
                self.add_error('peca', "Essa peça não pertence ao modelo deste item.")
            elif ItemFichaPeca.objects.filter(item_ficha=item_ficha, peca=peca).exists():
                self.add_error('peca', "Essa peça já foi adicionada a este modelo, nesta ficha.")

        if self.ficha:
            eh_numerada = self.ficha.tipo == Ficha.Tipo.NUMERADA
            if eh_numerada and not quantidade_planejada:
                self.add_error('quantidade_planejada', "Defina a quantidade planejada para a peça.")
            elif not eh_numerada and quantidade_planejada:
                cleaned_data['quantidade_planejada'] = None
        return cleaned_data

    def save(self):
        return ItemFichaPeca.objects.create(
            item_ficha=self.cleaned_data['item_ficha'],
            peca=self.cleaned_data['peca'],
            quantidade_planejada=self.cleaned_data.get('quantidade_planejada')
        )


class ItemFichaChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.modelo.numero} (Nº {obj.numeracao})"


class RegistroProducaoForm(forms.ModelForm):
    class Meta:
        model = RegistroProducao
        fields = ['item_ficha', 'peca', 'quantidade_produzida', 'quantidade_perda']
        labels = {
            'item_ficha': 'Modelo',
            'peca': 'Peça (opcional)',
            'quantidade_produzida': 'Quantidade produzida',
            'quantidade_perda': 'Quantidade perdida (opcional)',
        }
        widgets = {
            'item_ficha': forms.Select(attrs={'class': 'form-select'}),
            'peca': forms.Select(attrs={'class': 'form-select'}),
            'quantidade_produzida': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'placeholder': 'Ex: 25'
            }),
            'quantidade_perda': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'placeholder': 'Ex: 2 (opcional)'
            }),
        }

    def __init__(self, *args, ficha=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ficha = ficha

        self.fields['peca'].required = False
        self.fields['quantidade_produzida'].required = False
        self.fields['quantidade_perda'].required = False
        self.fields['peca'].empty_label = "---------"

        if ficha:
            self.fields['item_ficha'].label_from_instance = lambda obj: f"{obj.modelo.numero} (Nº {obj.numeracao})"
            self.fields['item_ficha'].queryset = ficha.itens.select_related('modelo')
            pecas_habilitadas_ids = ItemFichaPeca.objects.filter(
                item_ficha__ficha=ficha
            ).values_list('peca_id', flat=True)
            self.fields['peca'].queryset = Peca.objects.filter(id__in=pecas_habilitadas_ids)

    def clean_item_ficha(self):
        item = self.cleaned_data['item_ficha']
        if self.ficha and item.ficha_id != self.ficha.id:
            raise forms.ValidationError("Esse modelo não pertence a esta ficha.")
        return item

    def clean_quantidade_produzida(self):
        qtd = self.cleaned_data.get('quantidade_produzida')
        if qtd is not None and qtd < 0:
            raise forms.ValidationError("Quantidade não pode ser negativa.")
        return qtd or 0

    def clean_quantidade_perda(self):
        perda = self.cleaned_data.get('quantidade_perda')
        if perda is not None and perda < 0:
            raise forms.ValidationError("Quantidade de perda não pode ser negativa.")
        return perda or 0

    def clean(self):
        cleaned_data = super().clean()
        item_ficha = cleaned_data.get('item_ficha')
        peca = cleaned_data.get('peca')

        qtd_produzida = cleaned_data.get('quantidade_produzida', 0)
        qtd_perda = cleaned_data.get('quantidade_perda', 0)

        if qtd_produzida == 0 and qtd_perda == 0:
            raise forms.ValidationError("Informe ao menos a quantidade produzida ou a quantidade perdida.")

        if peca and item_ficha:
            if not ItemFichaPeca.objects.filter(item_ficha=item_ficha, peca=peca).exists():
                self.add_error('peca', "Essa peça não foi habilitada para este modelo, nesta ficha.")

        return cleaned_data