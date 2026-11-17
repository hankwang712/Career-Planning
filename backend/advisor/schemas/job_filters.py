from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cities: list[str] = Field(default_factory=list, max_length=10)
    candidate_education: Literal["中专", "高中", "大专", "本科", "硕士", "博士"] | None = None
    min_monthly_salary: int | None = Field(default=None, ge=0, le=1000000)
    max_monthly_salary: int | None = Field(default=None, ge=0, le=1000000)
    include_unknown: bool = True

    @model_validator(mode="after")
    def valid_range(self):
        if any(not city.strip() for city in self.cities):
            raise ValueError("城市不能为空")
        self.cities = list(dict.fromkeys(city.removesuffix("市") for city in self.cities))
        if (self.min_monthly_salary is not None and self.max_monthly_salary is not None
                and self.min_monthly_salary > self.max_monthly_salary):
            raise ValueError("最低月薪不能高于最高月薪")
        return self
