from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum


class Usuario(AbstractUser):
    class Tipo(models.TextChoices):
        ADMIN = 'admin', 'Administrador'
        SUPERVISOR = 'supervisor', 'Supervisor'

    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.SUPERVISOR)
    setor = models.ForeignKey('Setor', on_delete=models.SET_NULL, null=True, blank=True, related_name='usuarios')

    def __str__(self):
        return self.get_full_name() or self.username

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'
    @property
    def is_admin(self):
        return self.tipo == self.Tipo.ADMIN

class Setor(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Setor'
        verbose_name_plural = 'Setores'

    def __str__(self):
        return self.nome

class Operador(models.Model):
    nome = models.CharField(max_length=150)
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, related_name='operadores')
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Operador'
        verbose_name_plural = 'Operadores'

    def __str__(self):
        return f"{self.nome} ({self.setor.nome})"

    

class Modelo(models.Model):
    numero = models.CharField(max_length=20, unique=True)
    tempo_fabricacao = models.DecimalField(
        max_digits=6, decimal_places=3,
        help_text="Tempo em minutos para fabricar 1 par completo"
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['numero']
        verbose_name = 'Modelo'
        verbose_name_plural = 'Modelos'

    def __str__(self):
        return f"{self.numero}"

    @property
    def pares_por_hora(self):
        """(60 / tempo de fabricação) * 2, arredondado com 1 casa decimal."""
        if not self.tempo_fabricacao:
            return Decimal("0")
        resultado = (Decimal("60") / self.tempo_fabricacao) * Decimal("2")
        return resultado.quantize(Decimal("0.0"), rounding=ROUND_HALF_UP)


class Peca(models.Model):
    modelo = models.ForeignKey(Modelo, on_delete=models.CASCADE, related_name='pecas')
    nome = models.CharField(max_length=100)
    tempo_fabricacao = models.DecimalField(
        max_digits=6, decimal_places=3,
        help_text="Tempo em minutos para fabricar 1 unidade dessa peça"
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        unique_together = ['modelo', 'nome']

    def __str__(self):
        return f"{self.nome} ({self.modelo.numero})"

    def clean(self):
        if self.tempo_fabricacao and self.modelo_id and self.tempo_fabricacao > self.modelo.tempo_fabricacao:
            raise ValidationError("O tempo da peça não pode ser maior que o tempo total do modelo.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def pares_por_hora(self):
        """(60 / tempo de fabricação) * 2, arredondado com 1 casa decimal."""
        if not self.tempo_fabricacao:
            return Decimal("0")
        resultado = (Decimal("60") / self.tempo_fabricacao) * Decimal("2")
        return resultado.quantize(Decimal("0.0"), rounding=ROUND_HALF_UP)


class Ficha(models.Model):
    class Tipo(models.TextChoices):
        PADRAO = 'padrao', 'Padrão'
        NUMERADA = 'numerada', 'Numerada'

    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='fichas')
    operador = models.ForeignKey(Operador, on_delete=models.PROTECT, related_name='fichas',null=False, blank=False )

    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    data_criacao = models.DateField(auto_now_add=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    total_planejado = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name="Total Planejado Geral",
        help_text="Quantidade total planejada para fichas numeradas."
    )

    def __str__(self):
        return f"Ficha #{self.pk} - {self.usuario} ({self.data_criacao:%d/%m/%Y})"


class ItemFicha(models.Model):
    """Um Modelo adicionado dentro de uma Ficha (o supervisor faz isso no começo do dia)."""
    ficha = models.ForeignKey(Ficha, on_delete=models.CASCADE, related_name='itens')
    modelo = models.ForeignKey(Modelo, on_delete=models.PROTECT)
    numeracao = models.PositiveBigIntegerField(help_text="Numeração do calçado")
    quantidade_planejada = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Só usado em fichas Numeradas: o 'X' de pares a produzir"
    )
    adicionado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['ficha', 'modelo', 'numeracao']

    def __str__(self):
        return f"{self.modelo} (Nº {self.numeracao}) em {self.ficha}"

    def clean(self):
        if self.numeracao is not None and (self.numeracao < 26 or self.numeracao > 45):
            raise ValidationError({'numeracao': "Informe uma numeração válida"})
        
        eh_numerada = self.ficha_id and self.ficha.tipo == Ficha.Tipo.NUMERADA
        if eh_numerada and not self.quantidade_planejada:
            raise ValidationError("Fichas numeradas exigem a quantidade planejada de pares.")
        if self.ficha_id and self.ficha.tipo == Ficha.Tipo.PADRAO and self.quantidade_planejada:
            raise ValidationError("Fichas padrão não devem ter quantidade planejada.")

    @property
    def tempo_estimado_total(self):
        """Quanto tempo (min) levaria pra produzir a quantidade planejada."""
        if self.quantidade_planejada:
            return self.quantidade_planejada * self.modelo.tempo_fabricacao
        return None
    
    # -- metodos para ficha NUMERADA ---
    def qtd_restante(self, total_produzido):
        """Quantos pares ainda faltam para atingir o planejado."""
        if self.quantidade_planejada is not None:
            return max(0,self.quantidade_planejada - total_produzido)
        return None
    
    def percentual_concluido(self, total_produzido):
        """porcentagem de progrresso da quantidade planejada"""
        if self.quantidade_planejada:
            progresso = (total_produzido / self.quantidade_planejada) * 100
            return min (100, round(progresso)) # limita a 100 porcento
        return None
    
    def tempo_restante_minutos(self, total_produzido):
        """minutos necessarios para fabricar os pares restantes"""
        restante = self.qtd_restante(total_produzido)
        if restante is not None:
            return restante * self.modelo.tempo_fabricacao
        return None 
    
    def tempo_restante_formatado(self, total_produzido):
        """Retorna o tempo restante formatado em texto (ex: '2h 15m' ou '45m')."""
        total_minutos = self.tempo_restante_minutos(total_produzido)
        
        if total_minutos is None:
            return None
        
        # Converte para número inteiro de minutos arredondando
        total_minutos = round(float(total_minutos))
        
        if total_minutos <= 0:
            return "Concluído"
            
        horas = total_minutos // 60
        minutos = total_minutos % 60
        
        if horas > 0:
            return f"{horas}h {minutos:02d}m"
        
        return f"{minutos}m"

    @property
    def total_perda(self):
        """Soma tudo que já foi registrado de perda para essa peça neste item."""
        total = self.item_ficha.registros.filter(peca=self.peca).aggregate(
            total=Sum('quantidade_perda')
        )['total']
        return total or 0
    
class RegistroProducao(models.Model):
    """Cada baixa dada de hora em hora, no Modelo ou numa Peça específica dele."""
    item_ficha = models.ForeignKey(ItemFicha, on_delete=models.CASCADE, related_name='registros')
    peca = models.ForeignKey(
        Peca, on_delete=models.PROTECT, null=True, blank=True,
        help_text="Deixe em branco se o registro for do par completo (modelo)"
    )
    quantidade_produzida = models.PositiveIntegerField(default=0) # Permite registro só de perda
    quantidade_perda = models.PositiveIntegerField(default=0, blank=True,help_text="Quantidade de peças/pares perdidos")

    registrado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        alvo = self.peca.nome if self.peca else self.item_ficha.modelo.numero
        return f"{alvo}: {self.quantidade_produzida} em {self.registrado_em:%d/%m %H:%M}"

    def clean(self):
        if self.peca_id and self.peca.modelo_id != self.item_ficha.modelo_id:
            raise ValidationError("Essa peça não pertence ao modelo desta ficha.")

    @property
    def meta_do_periodo(self):
        """Quanto deveria ter sido produzido nessa hora (pares/hora do modelo ou da peça)."""
        alvo = self.peca if self.peca else self.item_ficha.modelo
        return alvo.pares_por_hora

    @property
    def dentro_da_meta(self):
        return self.quantidade_produzida >= self.meta_do_periodo
    
    @property
    def diferenca_meta(self):
        """
        Retorna a diferença em relação à meta.
        Positivo = Produziu a mais (ex: +5)
        Negativo = Ficou devendo (ex: -12)
        Zero = Exatamente na meta (0)
        """
        return self.quantidade_produzida - self.meta_do_periodo

    @property
    def qtd_planejada(self):
        """Retorna a quantidade planejada associada a este registro (peça ou modelo)."""
        if self.item_ficha.ficha.tipo != 'numerada':
            return None
        if self.peca_id:
            hab = self.item_ficha.pecas_habilitadas.filter(peca_id=self.peca_id).first()
            return hab.quantidade_planejada if hab else None
        return self.item_ficha.quantidade_planejada
    

class ItemFichaPeca(models.Model):
    """
    Habilita uma Peça específica pra ser registrada dentro de um ItemFicha
    (ou seja: dentro de UM modelo, DENTRO de UMA ficha). Sem isso, a peça
    não aparece como opção no form de Registrar Produção.
    """
    item_ficha = models.ForeignKey(ItemFicha, on_delete=models.CASCADE, related_name='pecas_habilitadas')
    peca = models.ForeignKey(Peca, on_delete=models.PROTECT, related_name='habilitacoes')
    quantidade_planejada = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Só usado em fichas Numeradas: o 'X' de peças a produzir"
    )
    adicionado_em = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        unique_together = ['item_ficha', 'peca']
 
    def __str__(self):
        return f"{self.peca.nome} habilitada em {self.item_ficha}"
 
    def clean(self):
        # 1. Validação de modelo correspondente
        if self.peca_id and self.item_ficha_id and self.peca.modelo_id != self.item_ficha.modelo_id:
            raise ValidationError("Essa peça não pertence ao modelo deste item da ficha.")

        # 2. Validações de quantidade planejada (usando eh_numerada)
        if self.item_ficha_id and hasattr(self.item_ficha, 'ficha'):
            eh_numerada = self.item_ficha.ficha.tipo == Ficha.Tipo.NUMERADA
            if eh_numerada and not self.quantidade_planejada:
                raise ValidationError("Fichas numeradas exigem a quantidade planejada para a peça.")
            if not eh_numerada and self.quantidade_planejada:
                raise ValidationError("Fichas padrão não devem ter quantidade planejada para a peça.")
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
 
    @property
    def total_produzido(self):
        """Soma tudo que já foi registrado pra essa peça, dentro deste item da ficha."""
        total = self.item_ficha.registros.filter(peca=self.peca).aggregate(
            total=Sum('quantidade_produzida')
        )['total']
        return total or 0

    @property
    def total_perda(self):
        retorno = self.item_ficha.registros.filter(
            peca=self.peca
        ).aggregate(total=Sum('quantidade_perda'))['total']
        return retorno or 0
 
    @property
    def meta_hora(self):
        return self.peca.pares_por_hora

    # --- MÉTODOS DE CÁLCULO (FICHA NUMERADA) ---
    def qtd_restante(self, total_produzido):
        if self.quantidade_planejada is not None:
            return max(0, self.quantidade_planejada - total_produzido)
        return None

    def percentual_concluido(self, total_produzido):
        if self.quantidade_planejada:
            progresso = (total_produzido / self.quantidade_planejada) * 100
            return min(100, round(progresso))
        return None

    def tempo_restante_minutos(self, total_produzido):
        restante = self.qtd_restante(total_produzido)
        if restante is not None and self.peca.tempo_fabricacao:
            return restante * self.peca.tempo_fabricacao
        return None

    def tempo_restante_formatado(self, total_produzido):
        total_minutos = self.tempo_restante_minutos(total_produzido)
        if total_minutos is None:
            return None
        
        total_minutos = round(float(total_minutos))
        if total_minutos <= 0:
            return "Concluído"
            
        horas = total_minutos // 60
        minutos = total_minutos % 60
        
        if horas > 0:
            return f"{horas}h {minutos:02d}m"
        return f"{minutos}m"